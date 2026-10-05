using BepInEx.Logging;
using DG.Tweening;
using HarmonyLib;
using Il2CppInterop.Runtime;
using Polytopia.Data;
using PolytopiaBackendBase.Common;
using PolytopiaBackendBase.Game;
using UnityEngine;
using UnityEngine.EventSystems;
using TerrainKind = Polytopia.Data.TerrainData.Type;

namespace BoardCaptureLoop;

public static class LoopMod
{
    private const string Id = "boardcaptureloop";
    private const int Total = 10;
    private static readonly System.Random Random = new();
    private static readonly TerrainKind[] Terrains =
    {
        TerrainKind.Field, TerrainKind.Forest, TerrainKind.Mountain, TerrainKind.Water, TerrainKind.Ocean
    };

    private static ManualLogSource? log;
    private static UIRoundButton_UI2? button;
    private static string? folder;
    private static int done, delay, menuFrames, sessionFrames;
    private static bool session, returning, ready, finishing;
    internal static bool IsRunning => folder != null;

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
        button.Text = "Loop";
        button.SetPosition(screenSize.safeRect.Left + 125f, screenSize.safeRect.Top - 50f);
    }

    private static void Start()
    {
        if (folder != null || session || GameManager.Instance.isLoadingGame || GameManager.Instance.isLevelLoaded) return;
        try
        {
            folder = Path.Combine(PolyMod.Plugin.BASE_PATH, "Maps", $"Loop-{DateTime.Now:yyyyMMdd-HHmmss-fff}");
            Directory.CreateDirectory(folder);
            done = 0;
            Next();
        }
        catch (Exception e) { Stop($"Could not start: {e}"); }
    }

    private static void Next()
    {
        ready = finishing = returning = false;
        session = true;
        delay = -1;
        menuFrames = sessionFrames = 0;
        int size = Random.Next(10, 21);
        log!.LogInfo($"Board {done + 1}/{Total}, size {size}");
        var settings = new GameSettings
        {
            GameName = "Board Capture Loop",
            GameType = EnumCache<GameType>.GetType(Id),
            BaseGameMode = EnumCache<GameMode>.GetType(Id),
            mapPreset = MapPreset.Dryland,
            MapSize = size
        };
        settings.SetUnlockedTribes(GameManager.GetPurchaseManager().GetUnlockedTribes(false));
        GameManager.StartingTribe = EnumCache<TribeType>.GetType(Id);
        GameManager.StartingTribeMix = TribeType.None;
        GameManager.StartingSkin = SkinType.Default;
        GameManager.PreliminaryGameSettings = settings;
        GameManager.PreliminaryGameSettings.OpponentCount = 0;
        GameManager.PreliminaryGameSettings.Difficulty = BotDifficulty.Frozen;
        Il2CppSystem.Nullable<Color> black = new(Color.black);
        UIBlackFader.FadeIn(0.5f, DelegateSupport.ConvertDelegate<Il2CppSystem.Action>(Open),
            "gamesettings.creatingworld", null, black);
    }

    private static void Open()
    {
        DOTween.KillAll(false);
        var manager = GameManager.Instance;
        if (manager.isLoadingGame) return;
        manager.SetLoadingGame(true);
        manager.client = new LocalClient();
        if (manager.settings.mapPreset == MapPreset.None) manager.settings.mapPreset = MapPreset.Continents;
        var client = manager.client;
        client.Reset();
        GameManager.Client.gameId = Il2CppSystem.Guid.NewGuid();
        var player = new PlayerState
        {
            Id = 1, AccountId = new(Il2CppSystem.Guid.Empty), AutoPlay = false,
            UserName = AccountManager.AliasInternal, tribe = GameManager.StartingTribe,
            tribeMix = GameManager.StartingTribeMix, skinType = GameManager.StartingSkin,
            hasChosenTribe = true
        };
        var state = new GameState
        {
            Version = VersionManager.GameVersion, Settings = manager.settings,
            PlayerStates = new Il2CppSystem.Collections.Generic.List<PlayerState>(), Seed = 0
        };
        state.PlayerStates.Add(player);
        GameStateUtils.SetPlayerColors(state);
        GameStateUtils.AddNaturePlayer(state);
        ushort size = (ushort)Math.Max(state.Settings.MapSize, MapDataExtensions.GetMinimumMapSize(state.PlayerCount));
        state.Map = new MapData(size, size);
        int index = 0;
        for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++)
                state.Map.Tiles[index++] = new TileData
                {
                    coordinates = new WorldCoordinates(x, y),
                    terrain = Terrains[Random.Next(Terrains.Length)],
                    climate = 0, altitude = 1, owner = 0, resource = null, improvement = null,
                    effects = new Il2CppSystem.Collections.Generic.List<TileData.EffectType>()
                };
        SerializationHelpers.FromByteArray<GameState>(SerializationHelpers.ToByteArray(state, state.Version),
            out GameState initial);
        GameManager.Client.initialGameState = initial;
        state.CommandStack.Add(new StartMatchCommand(1));
        GameManager.Client.hasInitializedSaveData = true;
        GameManager.Client.UpdateGameStateImmediate(state, StateUpdateReason.GameCreated);
        GameManager.Client.PrepareSession();
        manager.LoadLevel();
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameManager), nameof(GameManager.OnGameReady))]
    private static void GameReady()
    {
        if (session && folder != null) delay = 3;
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameManager), nameof(GameManager.Update))]
    private static void Tick()
    {
        if (folder == null) return;
        var manager = GameManager.Instance;
        if (ready && !session && !manager.isLevelLoaded)
        {
            if (++menuFrames < (finishing ? 30 : 3)) return;
            if (finishing) Finish();
            else if (!manager.isLoadingGame) TryNext();
            return;
        }
        if (!session) return;
        if (++sessionFrames > 1800)
        {
            Stop("Timed out waiting for the board to render.");
            GameManager.ReturnToMenu();
            return;
        }
        if (!manager.isLevelLoaded || delay < 0 || delay-- > 0) return;
        session = false;
        try
        {
            int size = (int)GameManager.GameState.Map.Width;
            if (size < 10 || size > 20) throw new InvalidOperationException($"Unexpected size: {size}");
            string prefix = Path.Combine(folder, $"map-{done + 1:D2}-{size}x{size}");
            if (File.Exists(prefix + ".png") || File.Exists(prefix + ".grid.json") || File.Exists(prefix + ".grid.png"))
                throw new IOException("Capture already exists.");
            Capture.Save(prefix, size);
            log!.LogInfo($"Captured {++done}/{Total}: {prefix}");
            finishing = done == Total;
            returning = true;
            GameManager.ReturnToMenu();
        }
        catch (Exception e)
        {
            Stop($"Capture failed: {e}");
            GameManager.ReturnToMenu();
        }
    }

    private static void TryNext()
    {
        try { Next(); }
        catch (Exception e) { Stop($"Next board failed: {e}"); }
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameManager), nameof(GameManager.ReturnToMenu))]
    private static void Returned()
    {
        if (folder == null) return;
        if (!returning) { Stop("Loop cancelled."); return; }
        returning = false;
        ready = true;
        menuFrames = 0;
    }

    private static void Finish()
    {
        string completed = folder!;
        folder = null;
        ready = finishing = false;
        try
        {
            GameManager.Instance.SetLoadingGame(false);
            Il2CppSystem.Nullable<Color> black = new(Color.black);
            UIBlackFader.FadeOut(0.25f, null, black);
        }
        catch (Exception e) { log!.LogWarning($"Could not clear loading view: {e}"); }
        log!.LogInfo($"Finished {Total} boards: {completed}");
        NotificationManager.Notify($"Generated {Total} boards in {completed}");
    }

    private static void Stop(string reason)
    {
        folder = null;
        session = returning = ready = finishing = false;
        log!.LogWarning(reason);
        NotificationManager.Notify(reason);
    }

    [HarmonyPostfix, HarmonyPatch(typeof(Tile), nameof(Tile.TileIsHidden))]
    [HarmonyPatch(typeof(Tile), nameof(Tile.IsHidden), MethodType.Getter)]
    private static void Reveal(ref bool __result)
    {
        if (session) __result = false;
    }

    [HarmonyPrefix, HarmonyPatch(typeof(ClientBase), nameof(ClientBase.SaveSession))]
    private static bool NoAutosave(ClientBase __instance) =>
        __instance.GameState.Settings.BaseGameMode != EnumCache<GameMode>.GetType(Id);

    [HarmonyPrefix, HarmonyPatch(typeof(LocalSaveFileUtils), nameof(LocalSaveFileUtils.DeleteAllSaveFilesOfType))]
    private static bool KeepSaves(GameType gameType) => gameType != EnumCache<GameType>.GetType(Id);

    [HarmonyPrefix, HarmonyPatch(typeof(LocalSaveFileUtils), nameof(LocalSaveFileUtils.DeleteSaveFile))]
    private static bool KeepSave(GameType gameType) => gameType != EnumCache<GameType>.GetType(Id);

    [HarmonyPrefix, HarmonyPatch(typeof(PlayerExtensions), nameof(PlayerExtensions.CountCapitals))]
    private static bool NoCapital(ref int __result)
    {
        if (!session) return true;
        __result = 0;
        return false;
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameLogicData), nameof(GameLogicData.GetAllTribes))]
    private static void HideInternalTribe(ref Il2CppSystem.Collections.Generic.List<TribeData> __result)
    {
        for (int i = 0; i < __result.Count; i++)
            if (__result[i].type == EnumCache<TribeType>.GetType(Id)) { __result.Remove(__result[i]); break; }
    }

    [HarmonyPostfix, HarmonyPatch(typeof(GameLogicData), nameof(GameLogicData.GetAllTribeTypes))]
    private static void HideInternalTribeType(ref Il2CppSystem.Collections.Generic.List<TribeType> __result) =>
        __result.Remove(EnumCache<TribeType>.GetType(Id));

    [HarmonyPostfix, HarmonyPatch(typeof(GameLogicData), nameof(GameLogicData.IsResourceVisibleToPlayer))]
    private static void RevealResource(ref bool __result)
    {
        if (session) __result = true;
    }

    [HarmonyPostfix, HarmonyPatch(typeof(CameraController), nameof(CameraController.Awake))]
    private static void CameraReady()
    {
        CameraController.Instance.maxZoom = 1000f;
        CameraController.Instance.techViewBounds = new(new(1000f, 1000f), CameraController.Instance.techViewBounds.size);
    }

    [HarmonyPostfix, HarmonyPatch(typeof(TechView), nameof(TechView.OnEnable))]
    private static void MoveTechTree(TechView __instance) =>
        __instance.techTreeContainer.parent.transform.position = new(1000f, 1000f);
}
