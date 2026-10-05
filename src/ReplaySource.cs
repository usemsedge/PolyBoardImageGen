using System.Buffers.Binary;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace BoardCaptureLoop;

public sealed class ReplaySnapshot
{
    private readonly byte[] bytes;
    public Guid Id { get; }
    public int Version { get; }
    public byte[] Bytes => (byte[])bytes.Clone();
    public string Sha256 { get; }
    internal ReplaySnapshot(Guid id, int version, byte[] bytes)
    {
        Id = id; Version = version; this.bytes = (byte[])bytes.Clone();
        Sha256 = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(bytes)).ToLowerInvariant();
    }
}

/// <summary>Downloads final snapshots only; native game-version compatibility is checked by the game layer.</summary>
public sealed class ReplaySource : IDisposable
{
    private readonly HttpClient client;
    private readonly bool ownsClient;
    private readonly TimeSpan timeout;
    private const int MaxResponseBytes = 64 * 1024 * 1024;
    public ReplaySource(HttpClient? client = null, TimeSpan? timeout = null)
    {
        this.client = client ?? new HttpClient(); ownsClient = client == null;
        this.timeout = timeout ?? TimeSpan.FromSeconds(60);
        if (this.timeout <= TimeSpan.Zero || this.timeout > TimeSpan.FromMinutes(5)) throw new ArgumentOutOfRangeException(nameof(timeout));
    }

    public async Task<ReplaySnapshot> FetchAsync(Guid id, string jwt, CancellationToken cancellationToken = default)
    {
        if (id == Guid.Empty) throw new ArgumentException("Replay ID cannot be empty.", nameof(id));
        if (string.IsNullOrWhiteSpace(jwt)) throw new InvalidOperationException("Sign in to Polytopia before downloading replays.");
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(cancellationToken);
        deadline.CancelAfter(timeout);
        try
        {
            using JsonDocument primary = await Post("get_game_view_model", id, jwt, deadline.Token).ConfigureAwait(false);
            if (TryData(primary.RootElement, out var data)) return Decode(id, data);
            using JsonDocument fallback = await Post("spectate_game", id, jwt, deadline.Token).ConfigureAwait(false);
            if (TryData(fallback.RootElement, out data)) return Decode(id, data);
            // Never echo server bodies or messages: they can include bearer credentials or private data.
            throw new InvalidDataException("Replay is unavailable or restricted, including spectate access.");
        }
        catch (OperationCanceledException) when (!cancellationToken.IsCancellationRequested)
        { throw new TimeoutException("Replay download timed out; retry later."); }
    }

    private async Task<JsonDocument> Post(string endpoint, Guid id, string jwt, CancellationToken token)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, "https://polytopia-prod.net/api/game/" + endpoint);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", jwt);
        request.Headers.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
        request.Content = new StringContent(JsonSerializer.Serialize(new { GameId = id.ToString("D") }), Encoding.UTF8, "application/json");
        using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, token).ConfigureAwait(false);
        if (response.StatusCode == HttpStatusCode.Unauthorized)
            throw new UnauthorizedAccessException("Replay authentication expired or was rejected. Sign in to Polytopia again.");
        if (!response.IsSuccessStatusCode) throw new HttpRequestException("Replay service returned HTTP " + (int)response.StatusCode + ".", null, response.StatusCode);
        if (response.Content.Headers.ContentLength > MaxResponseBytes) throw new InvalidDataException("Replay response exceeds the download limit.");
        using var body = await response.Content.ReadAsStreamAsync(token).ConfigureAwait(false);
        using var memory = new MemoryStream();
        var buffer = new byte[81920];
        int count;
        while ((count = await body.ReadAsync(buffer.AsMemory(), token).ConfigureAwait(false)) != 0)
        {
            if (memory.Length + count > MaxResponseBytes) throw new InvalidDataException("Replay response exceeds the download limit.");
            memory.Write(buffer, 0, count);
        }
        try { return JsonDocument.Parse(memory.ToArray()); }
        catch (JsonException) { throw new InvalidDataException("Replay service returned malformed JSON."); }
    }

    private static bool TryData(JsonElement root, out JsonElement data)
    {
        data = default;
        return root.ValueKind == JsonValueKind.Object && root.TryGetProperty("success", out var success) &&
            success.ValueKind == JsonValueKind.True && root.TryGetProperty("data", out data) && data.ValueKind == JsonValueKind.Object;
    }

    private static ReplaySnapshot Decode(Guid id, JsonElement data)
    {
        if (!data.TryGetProperty("state", out var state) || state.ValueKind != JsonValueKind.Number || !state.TryGetInt32(out int value) || value != 4)
            throw new InvalidDataException("Replay is not ended; only final ended states can be captured.");
        if (!data.TryGetProperty("currentGameStateData", out var blob) || blob.ValueKind != JsonValueKind.String || string.IsNullOrWhiteSpace(blob.GetString()))
            throw new InvalidDataException("Replay has no final currentGameStateData snapshot.");
        byte[] bytes;
        try { bytes = Convert.FromBase64String(blob.GetString()!); }
        catch (FormatException) { throw new InvalidDataException("Final replay snapshot is not valid base64."); }
        if (bytes.Length <= 8) throw new InvalidDataException("Final replay snapshot is truncated.");
        int wrapper = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(0, 4));
        int payload = BinaryPrimitives.ReadInt32LittleEndian(bytes.AsSpan(4, 4));
        if (wrapper <= 0 || payload != wrapper) throw new InvalidDataException("Replay serialization wrapper and payload versions do not agree.");
        return new ReplaySnapshot(id, wrapper, bytes);
    }
    public void Dispose() { if (ownsClient) client.Dispose(); }
}
