using BepInEx.Logging;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Polytopia.Data;
using PolytopiaBackendBase.Common;
using PolytopiaBackendBase.Game;
using UnityEngine;
using UnityEngine.EventSystems;

namespace BoardCaptureLoop;

public static class LoopMod
{
    private const string Id = "boardcaptureloop";
    private const int Total = 10;
    private const string CsvName = "Polytopia Tribe Evaluator Calculator - Google Form.csv";
    private enum Phase { Idle, Next, Download, Load, Render, Unload }
    private static ManualLogSource? log;
    private static UIRoundButton_UI2? button;
    private static ReplayCatalog? catalog;
    private static ReplaySource? source;
    private static ReplayOutput? output;
    private static IReadOnlyList<ReplayEntry>? queue;
    private static ReplayEntry? entry;
    private static ReplaySnapshot? snapshot;
    private static ReplayAttempt? attempt;
    private static CaptureSession? session;
    private static CancellationTokenSource? cancellation;
    private static Task<ReplaySnapshot>? download;
    private static readonly List<(int Index, byte Id)> players = new();
    private static Phase phase;
    private static DateTime deadline;
    private static int next, done, failed, skipped, view, unloadFrames;
    private static bool internalReturn, cancelled, attemptFailed;
    private static string? failure;
    internal static bool IsRunning => phase != Phase.Idle;
    internal static bool OwnsCaptureClient => session != null && session.OwnsCurrentClient;
    private static bool FullReveal => OwnsCaptureClient && session!.Revealed;

    public static void Load(ManualLogSource logger)
    {
        log = logger;
        Harmony.CreateAndPatchAll(typeof(LoopMod));
        PolyMod.Loader.AddGameMode(Id, (UIButtonBase.ButtonAction)OnStart, false);
        PolyMod.Loader.AddPatchDataType("gameType", typeof(GameType));
        PolyMod.Loader.AddPatchDataType("gameMode", typeof(GameMode));
        static void OnStart(int unused, BaseEventData eventData) => Start();
    }

    [HarmonyPostfix, HarmonyPatch(typeof(StartScreen_UI2), nameof(StartScreen_UI2.Init))]
    private static void MenuInit(StartScreen_UI2 __instance, RectTransform transform)
    {
        button = UILibrary.NewRoundButton(transform).SetStyle(UIButtonBase_UI2.ButtonStyle.Suggested);
        button.OnClickedSignal.Add(DelegateSupport.ConvertDelegate<Il2CppSystem.Action>(Start));
    }

    [HarmonyPostfix, HarmonyPatch(typeof(StartScreen_UI2), nameof(StartScreen_UI2.RunLayout))]
    private static void MenuLayout(StartScreen_UI2 __instance, ScreenBase_UI2.ScreenSize screenSize)
    {
        if (button == null) return;
        button.iconContainer.gameObject.SetActive(false);
        button.outline.gameObject.SetActive(false);
        button.bg.color = Color.white;
        button.Text = IsRunning ? "Cancel" : "Loop";
        button.SetPosition(screenSize.safeRect.Left + 125f, screenSize.safeRect.Top - 50f);
    }

    private static void Start()
    {
        if (IsRunning) { Cancel(); return; }
        var manager = GameManager.Instance;
        if (manager.isLoadingGame || manager.isLevelLoaded) return;
        try
        {
            string csv = Environment.GetEnvironmentVariable("BOARDCAPTURELOOP_CSV") ?? Path.Combine(PolyMod.Plugin.MODS_PATH, CsvName);
            catalog = ReplayCatalog.Open(csv);
            source = new ReplaySource();
            output = new ReplayOutput(Path.Combine(PolyMod.Plugin.BASE_PATH, "Maps", "replay-captures"));
            foreach (ReplayEntry completed in catalog.GetCompleted())
            {
                if (output.TryRecover(completed.Id, out _)) continue;
                catalog.Mark(completed.Id, ReplayStatus.RetryableError, error: "Completed capture artifacts are missing or corrupt; queued for recovery.");
                log!.LogWarning($"Capture {completed.Id:D} is missing or corrupt; queued for recovery.");
            }
            queue = catalog.GetPending(); // One ordered snapshot: a failure is attempted once this run.
            cancellation = new CancellationTokenSource();
            next = done = failed = skipped = 0;
            cancelled = false;
            SetPhase(Phase.Next);
            log!.LogInfo($"Replay capture started: {queue.Count} unfinished links.");
        }
        catch (Exception e) { Finish("Could not start replay capture: " + e.Message); }
    }

    private static void SetPhase(Phase value)
    {
        phase = value;
        deadline = DateTime.UtcNow.AddSeconds(value == Phase.Download ? 120 : 60);
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameManager), nameof(GameManager.Update))]
    private static void Tick()
    {
        if (!IsRunning) return;
        try
        {
            if (Input.GetKeyDown(KeyCode.Escape)) Cancel();
            var manager = GameManager.Instance;
            if (phase == Phase.Unload)
            {
                if (manager.isLevelLoaded || manager.isLoadingGame)
                {
                    if (DateTime.UtcNow > deadline)
                    {
                        // Keep protection and ownership until scene teardown really finishes.
                        // Restoring another client into a still-live capture scene is unsafe.
                        deadline = DateTime.UtcNow.AddSeconds(60);
                        cancelled = true;
                        log!.LogWarning("Waiting for replay scene teardown; capture is cancelled and save protection remains active.");
                        ReturnToMenu();
                    }
                    return;
                }
                if (++unloadFrames < 3) return;
                session?.Dispose();
                session = null;
                if (cancelled) { Finish("Replay capture cancelled."); return; }
                if (attemptFailed) { EndFailedAttempt(); return; }
                if (++view < 4) SetPhase(Phase.Load);
                else Publish();
                return;
            }
            if (cancelled) { Finish("Replay capture cancelled."); return; }
            if (DateTime.UtcNow > deadline) throw new TimeoutException("Timed out during " + phase.ToString().ToLowerInvariant() + ".");
            switch (phase)
            {
                case Phase.Next: NextReplay(); break;
                case Phase.Download:
                    if (download == null || !download.IsCompleted) return;
                    snapshot = download.GetAwaiter().GetResult();
                    download = null;
                    ValidateReplay();
                    break;
                case Phase.Load:
                    if (manager.isLevelLoaded || manager.isLoadingGame) return;
                    var player = players[view % 2];
                    session = new CaptureSession(snapshot!.Bytes, entry!.Id, player.Index, player.Id, view >= 2);
                    SetPhase(Phase.Render);
                    log!.LogInfo($"Replay load starting: player {session.PlayerId}, {(session.Revealed ? "revealed" : "normal")}.");
                    session.Load();
                    log!.LogInfo("Replay load stage: " + session.LoadStage + ".");
                    break;
                case Phase.Render:
                    if (session == null || !session.Ready || !manager.isLevelLoaded) return;
                    if (!session.Configured) { session.ConfigureView(); return; }
                    if (MapRenderer.Current == null || !MapRenderer.Current.IsRendered) { session.SettledFrames = 0; return; }
                    if (++session.SettledFrames < 5) return;
                    string mode = session.Revealed ? "revealed" : "normal";
                    session.CaptureTo(Path.Combine(attempt!.DirectoryPath, $"player-{session.PlayerId}-{mode}"));
                    BeginUnload();
                    break;
            }
        }
        catch (Exception e) { FailAttempt(e); }
    }

    private static void NextReplay()
    {
        if (done >= Total || next >= queue!.Count)
        {
            Finish($"Captured {done}/{Total} replays ({done * 4} clean images, overlays, and metadata files each); skipped {skipped}, retryable failures {failed}.");
            return;
        }
        entry = queue[next++];
        snapshot = null;
        attempt = null;
        attemptFailed = false;
        failure = null;
        view = 0;
        if (output!.TryRecover(entry.Id, out ReplayManifest? manifest))
        {
            catalog!.Mark(entry.Id, ReplayStatus.Done, manifest!.DirectoryPath);
            log!.LogInfo($"Recovered published capture {entry.Id:D} without rendering again.");
            return;
        }
        // Access native account/path APIs only here on the Unity thread. Reading the
        // credential and HTTP/JSON processing are off-thread; never retain/log tokens.
        string tokenPath;
        try
        {
            tokenPath = PolytopiaBackendAdapter.Instance?.tokenLocalPath ?? FindTokenPath(Application.persistentDataPath);
            if (!File.Exists(tokenPath)) throw new FileNotFoundException();
        }
        catch (Exception e) when (e is IOException || e is UnauthorizedAccessException || e is InvalidOperationException)
        {
            throw new UnauthorizedAccessException("Game authentication is unavailable; sign in before capturing.");
        }
        Guid replayId = entry.Id;
        CancellationToken token = cancellation!.Token;
        ReplaySource activeSource = source!;
        download = Task.Run(async () =>
        {
            string jwt;
            try { jwt = (await File.ReadAllTextAsync(tokenPath, token).ConfigureAwait(false)).Trim(); }
            catch (Exception e) when (e is IOException || e is UnauthorizedAccessException)
            { throw new UnauthorizedAccessException("Game authentication is unavailable; sign in before capturing."); }
            if (string.IsNullOrWhiteSpace(jwt)) throw new UnauthorizedAccessException("Game authentication is unavailable; sign in before capturing.");
            return await activeSource.FetchAsync(replayId, jwt, token).ConfigureAwait(false);
        }, token);
        // Observe abandoned faulted tasks without permitting callbacks into a later run.
        _ = download.ContinueWith(t => { _ = t.Exception; }, CancellationToken.None, TaskContinuationOptions.OnlyOnFaulted, TaskScheduler.Default);
        SetPhase(Phase.Download);
        log!.LogInfo($"Downloading replay {entry.Id:D} ({done + 1}/{Total}).");
    }

    private static string FindTokenPath(string persistentPath)
    {
        var files = Directory.EnumerateDirectories(persistentPath)
            .Select(directory => Path.Combine(directory, "jwtToken"))
            .Where(File.Exists).OrderByDescending(File.GetLastWriteTimeUtc);
        return files.FirstOrDefault() ?? throw new InvalidOperationException("Game authentication is unavailable; sign in before capturing.");
    }

    private static void ValidateReplay()
    {
        var state = CaptureSession.ReadState(snapshot!.Bytes);
        if (state.PlayerStates == null) throw new InvalidDataException("Replay is missing its participants.");
        players.Clear();
        for (int i = 0; i < state.PlayerStates.Count; i++)
        {
            byte playerId = state.PlayerStates[i].Id;
            if (playerId != PlayerState.NATURE_PLAYER_ID) players.Add((i, playerId));
        }
        if (players.Count != 2 || GameStateUtils.NumPlayersExcludingNature(state) != 2)
        {
            catalog!.Mark(entry!.Id, ReplayStatus.SkippedNonTwoPlayer, error: $"Replay has {players.Count} actual participants.");
            skipped++;
            SetPhase(Phase.Next);
            return;
        }
        if (players[0].Id == players[1].Id || players.Any(p => p.Id == PlayerState.NO_PLAYER_ID))
            throw new InvalidDataException("Replay participants have invalid or duplicate player identities.");
        int size = CaptureSession.ValidateMap(state);
        attempt = output!.Begin(entry!.Id, snapshot.Version, snapshot.Sha256);
        log!.LogInfo($"Rendering {size}x{size} replay {entry.Id:D}, players {players[0].Id} and {players[1].Id} (including eliminated players).");
        SetPhase(Phase.Load);
    }

    private static void Publish()
    {
        ReplayManifest manifest = output!.Commit(attempt!, snapshot == null ? throw new InvalidOperationException("Missing replay snapshot.") : CaptureSession.ValidateMap(CaptureSession.ReadState(snapshot.Bytes)), players.Select(p => (int)p.Id).ToArray());
        // A crash or catalog conflict here is recovered from the manifest next start.
        attempt = null;
        catalog!.Mark(entry!.Id, ReplayStatus.Done, manifest.DirectoryPath);
        done++;
        log!.LogInfo($"Captured {done}/{Total}: {manifest.DirectoryPath}");
        snapshot = null;
        SetPhase(Phase.Next);
    }

    private static void FailAttempt(Exception exception)
    {
        failure = exception is OperationCanceledException ? "Capture cancelled." : exception.Message;
        // Do not log request bodies, authentication, or exception object graphs.
        log!.LogWarning($"Replay {entry?.Id.ToString("D") ?? "queue"} failed{(session == null ? "" : " during " + session.LoadStage)}: {failure}");
        attemptFailed = true;
        if (exception is UnauthorizedAccessException)
        {
            // A rejected/missing account token affects the whole queue, not one replay.
            try { if (entry != null) catalog!.Mark(entry.Id, ReplayStatus.RetryableError, error: failure); }
            catch (Exception e) { log!.LogWarning("Could not record authentication failure: " + e.Message); }
            failed++;
            Finish("Replay capture stopped: " + failure);
            return;
        }
        if (session != null || GameManager.Instance.isLevelLoaded || GameManager.Instance.isLoadingGame)
        {
            BeginUnload();
            return;
        }
        EndFailedAttempt();
    }

    private static void EndFailedAttempt()
    {
        try
        {
            if (attempt != null) output!.Abandon(attempt);
            attempt = null;
            if (entry != null) catalog!.Mark(entry.Id, ReplayStatus.RetryableError, error: failure ?? "Replay capture failed.");
            failed++;
            snapshot = null;
            download = null;
            SetPhase(Phase.Next);
        }
        catch (Exception e) { Finish("Capture stopped to preserve CSV/output progress: " + e.Message); }
    }

    private static void BeginUnload()
    {
        unloadFrames = 0;
        SetPhase(Phase.Unload);
        if (session != null && !session.LevelLoadRequested && !GameManager.Instance.isLevelLoaded)
        {
            // Preparation failed before any scene request. ReturnToMenu cannot clear
            // this loading flag at the menu; restore our client/settings immediately.
            session.Dispose();
            session = null;
            log!.LogInfo("Replay preparation rolled back before opening a level.");
            return;
        }
        ReturnToMenu();
    }

    private static void ReturnToMenu()
    {
        internalReturn = true;
        try { GameManager.ReturnToMenu(); }
        finally { internalReturn = false; }
    }

    private static void Cancel()
    {
        if (!IsRunning || cancelled) return;
        cancelled = true;
        cancellation?.Cancel();
        if (session != null || GameManager.Instance.isLevelLoaded || GameManager.Instance.isLoadingGame) BeginUnload();
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameManager), nameof(GameManager.ReturnToMenu))]
    private static void Returned()
    {
        if (!IsRunning || internalReturn) return;
        cancelled = true;
        cancellation?.Cancel();
        unloadFrames = 0;
        SetPhase(Phase.Unload);
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameManager), nameof(GameManager.OnGameReady))]
    private static void GameReady()
    {
        if (session != null && session.OwnsCurrentClient) session.Ready = true;
    }

    private static void Finish(string message)
    {
        phase = Phase.Idle;
        cancellation?.Cancel();
        try
        {
            session?.Dispose();
            if (attempt != null) output?.Abandon(attempt);
        }
        catch (Exception e) { log?.LogWarning("Capture cleanup failed: " + e.Message); }
        finally
        {
            session = null;
            attempt = null;
            snapshot = null;
            download = null;
            source?.Dispose();
            source = null;
            catalog?.Dispose();
            catalog = null;
            cancellation?.Dispose();
            cancellation = null;
            entry = null;
            queue = null;
        }
        log?.LogInfo(message);
        NotificationManager.Notify(message);
        if (button != null) button.Text = "Loop";
    }

    [HarmonyPostfix, HarmonyPatch(typeof(Tile), nameof(Tile.TileIsHidden))]
    [HarmonyPatch(typeof(Tile), nameof(Tile.IsHidden), MethodType.Getter)]
    private static void Reveal(ref bool __result) { if (FullReveal) __result = false; }

    [HarmonyPostfix, HarmonyPatch(typeof(GameLogicData), nameof(GameLogicData.IsResourceVisibleToPlayer))]
    private static void RevealResource(ref bool __result) { if (FullReveal) __result = true; }

    [HarmonyPrefix, HarmonyPatch(typeof(ClientBase), nameof(ClientBase.SaveSession))]
    [HarmonyPatch(typeof(ClientBase), nameof(ClientBase.SaveLocalGameData))]
    [HarmonyPatch(typeof(ClientBase), nameof(ClientBase.SaveHotSeatGameState))]
    private static bool NoAutosave(ClientBase __instance) => session == null || !session.Owns(__instance);

    [HarmonyPrefix, HarmonyPatch(typeof(LocalSaveFileUtils), nameof(LocalSaveFileUtils.DeleteAllSaveFilesOfType))]
    [HarmonyPatch(typeof(LocalSaveFileUtils), nameof(LocalSaveFileUtils.DeleteSaveFile))]
    private static bool KeepSaves(GameType gameType) => !OwnsCaptureClient || gameType != session!.GameType;

    [HarmonyPrefix, HarmonyPatch(typeof(GameManager), nameof(GameManager.TryCreateAndExecuteAICommands))]
    [HarmonyPatch(typeof(GameManager), nameof(GameManager.MatchEnded))]
    [HarmonyPatch(typeof(GameManager), nameof(GameManager.SendEndGameEvents))]
    [HarmonyPatch(typeof(GameManager), nameof(GameManager.TrackFinishedGame))]
    private static bool KeepFinalState() => !OwnsCaptureClient;

    [HarmonyPrefix, HarmonyPatch(typeof(ClientBase), nameof(ClientBase.SendCommand))]
    [HarmonyPatch(typeof(ClientBase), nameof(ClientBase.ReceiveCommand), new[] { typeof(CommandBase) })]
    private static bool NoCommands(ClientBase __instance) => session == null || !session.Owns(__instance);

    [HarmonyPrefix, HarmonyPatch(typeof(Timeline), nameof(Timeline.Play))]
    private static bool NoReplayPlayback() => !OwnsCaptureClient;

    [HarmonyPrefix, HarmonyPatch(typeof(GameOverReaction), nameof(GameOverReaction.Execute))]
    private static bool NoEndOverlay(Il2CppSystem.Action onComplete)
    {
        if (!OwnsCaptureClient) return true;
        onComplete?.Invoke();
        return false;
    }

    // Retain compatibility with the packaged legacy tribe, but never use it to
    // manufacture replay states or apply gameplay/capital overrides.
    [HarmonyPostfix, HarmonyPatch(typeof(GameLogicData), nameof(GameLogicData.GetAllTribes))]
    private static void HideInternalTribe(ref Il2CppSystem.Collections.Generic.List<TribeData> __result)
    {
        for (int i = 0; i < __result.Count; i++)
            if (__result[i].type == EnumCache<TribeType>.GetType(Id)) { __result.Remove(__result[i]); break; }
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameLogicData), nameof(GameLogicData.GetAllTribeTypes))]
    private static void HideInternalTribeType(ref Il2CppSystem.Collections.Generic.List<TribeType> __result) =>
        __result.Remove(EnumCache<TribeType>.GetType(Id));
}
