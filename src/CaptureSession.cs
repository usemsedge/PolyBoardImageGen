using PolytopiaBackendBase.Game;
using UnityEngine;

namespace BoardCaptureLoop;

// All methods in this class run on the Unity thread. Each view owns an independent
// native state/client, and retains its ownership until the level has unloaded.
internal sealed class CaptureSession : IDisposable
{
    private readonly ClientBase? previousClient;
    private readonly GameSettings previousSettings;
    private readonly bool previousFog, previousSharedFog, previousLoading;
    private readonly byte[] expectedState;
    private readonly GameState state;
    private bool disposed;

    internal ReplayClient Client { get; }
    internal int PlayerIndex { get; }
    internal byte PlayerId { get; }
    internal bool Revealed { get; }
    internal int Size { get; }
    internal GameType GameType => state.Settings.GameType;
    internal bool Ready { get; set; }
    internal bool LevelLoadRequested { get; private set; }
    internal string LoadStage { get; private set; } = "created";
    internal bool Configured { get; private set; }
    internal int SettledFrames { get; set; }
    internal bool OwnsCurrentClient => Owns(GameManager.Instance.client);

    internal CaptureSession(byte[] bytes, Guid replayId, int playerIndex, byte playerId, bool revealed)
    {
        state = ReadState(bytes);
        Size = ValidateMap(state);
        if (playerIndex < 0 || playerIndex >= state.PlayerStates.Count || state.PlayerStates[playerIndex].Id != playerId)
            throw new InvalidDataException("Replay player identity changed between views.");
        PlayerIndex = playerIndex;
        PlayerId = playerId;
        Revealed = revealed;
        previousClient = GameManager.Instance.client;
        previousSettings = GameManager.Instance.settings;
        previousLoading = GameManager.Instance.isLoadingGame;
        previousFog = SettingsUtils.ReplayEnableFog;
        previousSharedFog = SettingsUtils.ReplaySharedFog;
        expectedState = SerializationHelpers.ToByteArray(state, state.Version);
        Client = new ReplayClient();
        Client.gameId = new Il2CppSystem.Guid(replayId.ToString());
    }

    internal static GameState ReadState(byte[] bytes)
    {
        if (!SerializationHelpers.PeekVersion(bytes, out int version) || !VersionManager.IsGameVersionSupported(version))
            throw new InvalidDataException("Replay serialization version is not supported by this game.");
        if (!SerializationHelpers.FromByteArray<GameState>(bytes, out GameState result, out int readVersion) || result == null)
            throw new InvalidDataException("The final replay state could not be deserialized.");
        if (readVersion != version || result.Version != version)
            throw new InvalidDataException("Replay serialization versions disagree; native upgrade is not verified.");
        return result;
    }

    internal static int ValidateMap(GameState state)
    {
        if (state.Map == null || state.PlayerStates == null || state.Settings == null)
            throw new InvalidDataException("Replay is missing its map, settings, or participants.");
        int size = state.Map.Width;
        if (size != state.Map.Height || size < 1 || size > 100)
            throw new InvalidDataException("Only square replay maps with sides between 1 and 100 tiles are supported.");
        if (state.Map.Tiles == null || state.Map.Tiles.Count != size * size)
            throw new InvalidDataException("Replay tile count does not match its dimensions.");
        return size;
    }

    internal bool Owns(ClientBase? client) => !disposed && client != null && client.Pointer == Client.Pointer;

    internal void Load()
    {
        var manager = GameManager.Instance;
        SettingsUtils.ReplaySharedFog = false;
        SettingsUtils.ReplayEnableFog = !Revealed;
        LoadStage = "installing replay client";
        // SetReplayClient normalizes manager.settings.GameType; never let it mutate
        // the original menu settings or the downloaded final-state settings.
        manager.settings = ReadState(expectedState).Settings;
        manager.SetReplayClient(Client);
        // Both snapshots are the final state: no command replay, fresh world creation,
        // starting command, or current-turn/player mutation is needed.
        Client.SetupWithFakeData(Client.gameId, ReadState(SerializationHelpers.ToByteArray(state, state.Version)), state);
        Client.currentViewingPlayer = PlayerIndex;
        Client.doAutoSwitchPlayers = false;
        Client.hasInitializedSaveData = true;
        Client.isUploadingHighscore = false;
        Client.hasUploadedHighScore = true;
        LoadStage = "initializing replay action manager";
        // Native SetupWithFakeData only assigns the two states and ID. PrepareSession
        // dereferences ActionManager before seeking; use the native factory, which
        // also wires its processing callbacks, with the final command cursor.
        Client.CreateOrResetActionManager(state.CurrentCommand);
        if (Client.ActionManager == null)
            throw new InvalidOperationException("Native replay action manager was not initialized.");
        LoadStage = "preparing replay session";
        manager.SetLoadingGame(true);
        Client.PrepareSession();
        LoadStage = "requesting replay level";
        // Set before the native call: a throwing call may already have started loading.
        LevelLoadRequested = true;
        manager.LoadLevel();
        LoadStage = "waiting for replay level";
    }

    internal bool ConfigureView()
    {
        if (!OwnsCurrentClient) throw new InvalidOperationException("The temporary replay client was replaced.");
        var replay = UnityEngine.Object.FindObjectOfType<ReplayInterface>();
        var renderer = MapRenderer.Current;
        if (replay == null || renderer == null || !renderer.IsRendered) return false;
        if (replay.timeline != null) replay.timeline.Pause();
        replay.SwitchPlayerPerspective(PlayerIndex); // PlayerStates index, never the byte player ID.
        if (Revealed) replay.SetNoFog(); else replay.SetNormalFog();
        if (!GameManager.IsPlayerViewing(PlayerId))
            throw new InvalidOperationException("The game did not select the requested replay perspective.");
        renderer.Refresh(true);
        renderer.ReRenderAllTiles();
        Configured = true;
        SettledFrames = 0;
        return true;
    }

    internal void CaptureTo(string prefix)
    {
        if (!OwnsCurrentClient || !Configured || !GameManager.IsPlayerViewing(PlayerId))
            throw new InvalidOperationException("Replay capture lost its viewing-player context.");
        // Fail closed if native session initialization or a background reaction advanced
        // or otherwise modified the final board. Never publish a plausible wrong view.
        byte[] actual = SerializationHelpers.ToByteArray(Client.GameState, state.Version);
        if (!expectedState.AsSpan().SequenceEqual(actual))
            throw new InvalidOperationException("Native replay initialization changed the final game state.");
        Capture.Save(prefix, Size);
    }

    public void Dispose()
    {
        if (disposed) return;
        // Restore directly before LoadLevel was requested, or after scene teardown.
        // Never restore an unrelated client into a live/in-flight capture scene.
        var currentManager = GameManager.Instance;
        if (LevelLoadRequested && (currentManager.isLevelLoaded || currentManager.isLoadingGame))
            throw new InvalidOperationException("Replay scene must finish unloading before restoring the previous client.");
        try
        {
            SettingsUtils.ReplayEnableFog = previousFog;
            SettingsUtils.ReplaySharedFog = previousSharedFog;
        }
        finally
        {
            var manager = GameManager.Instance;
            if (Owns(manager.client))
            {
                manager.client = previousClient;
                manager.settings = previousSettings;
                manager.SetLoadingGame(previousLoading);
            }
            disposed = true;
        }
    }
}
