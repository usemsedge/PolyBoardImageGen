using System.Buffers.Binary;
using System.IO.Compression;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using BoardCaptureLoop;
using Xunit;

namespace BoardCaptureLoopTests;

public sealed class ReplayTests : IDisposable
{
    private readonly string directory = Path.Combine(Path.GetTempPath(), "BoardCaptureTests-" + Guid.NewGuid().ToString("N"));
    private static readonly Guid A = Guid.Parse("eb7c997c-71e3-4eae-b973-08dd0c9ba532");
    private static readonly Guid B = Guid.Parse("5ece47cd-40ea-46e5-2369-08dd1f786eb4");
    public ReplayTests() { Directory.CreateDirectory(directory); }
    public void Dispose() { Directory.Delete(directory, true); }
    private string Csv(string text, bool bom = false)
    {
        string path = Path.Combine(directory, "queue.csv");
        File.WriteAllText(path, text, new UTF8Encoding(bom)); return path;
    }
    private static string Link(Guid id) => "https://share.polytopia.io/g/" + id;

    [Fact]
    public void CatalogPreservesBomQuotedColumnsAndMirrorsDuplicateStatus()
    {
        string original = "REPLAY LINK,notes\r\n" + Link(A) + ",\"line1\r\nline2, \"\"quoted\"\"\"\r\n" + Link(B) + ",other\r\n" + Link(A).ToUpperInvariant().Replace("/G/", "/g/") + ",duplicate\r\n";
        string path = Csv(original, true);
        byte[] before = File.ReadAllBytes(path);
        using (var catalog = ReplayCatalog.Open(path))
        {
            Assert.Equal(new[] { A, B }, catalog.GetPending().Select(e => e.Id));
            Assert.Equal(before, File.ReadAllBytes(path));
            catalog.Mark(A, ReplayStatus.Done, "maps/output");
            Assert.Equal(new[] { B }, catalog.GetPending().Select(e => e.Id));
            Assert.Throws<IOException>(() => ReplayCatalog.Open(path));
        }
        byte[] after = File.ReadAllBytes(path);
        Assert.Equal(new byte[] { 239, 187, 191 }, after.Take(3));
        Assert.Equal(before, File.ReadAllBytes(path + ".bak"));
        string updated = File.ReadAllText(path);
        Assert.Contains("\"line1\r\nline2, \"\"quoted\"\"\"", updated);
        Assert.Equal(2, updated.Split("done,maps/output").Length - 1);
        using var reopened = ReplayCatalog.Open(path);
        Assert.Equal(new[] { B }, reopened.GetPending().Select(e => e.Id));
    }

    [Fact]
    public void CatalogRetriesNextRunButNotAgainThisRunAndSkipsTerminalDuplicates()
    {
        string path = Csv("REPLAY LINK,capture_status\r\n" + Link(A) + ",\r\n" + Link(A) + ",done\r\n" + Link(B) + ",retryable_error\r\n");
        using (var catalog = ReplayCatalog.Open(path))
        {
            Assert.Equal(B, Assert.Single(catalog.GetPending()).Id);
            catalog.Mark(B, ReplayStatus.RetryableError, error: "temporary");
            Assert.Empty(catalog.GetPending());
        }
        using (var catalog = ReplayCatalog.Open(path))
        {
            Assert.Equal(B, Assert.Single(catalog.GetPending()).Id);
            catalog.Mark(B, ReplayStatus.SkippedNonTwoPlayer);
        }
        using var final = ReplayCatalog.Open(path);
        Assert.Empty(final.GetPending());
    }

    [Fact]
    public void CatalogRequeuesDamagedCompletedOutputsInTheSameRun()
    {
        string path = Csv("REPLAY LINK,capture_status\r\n" + Link(A) + ",done\r\n");
        using var catalog = ReplayCatalog.Open(path);
        Assert.Equal(A, Assert.Single(catalog.GetCompleted()).Id);
        catalog.Mark(A, ReplayStatus.RetryableError, error: "Missing artifacts");
        Assert.Empty(catalog.GetCompleted());
        Assert.Equal(A, Assert.Single(catalog.GetPending()).Id);
    }

    [Fact]
    public void CatalogRejectsAmbiguousHeaders()
    {
        string path = Csv("REPLAY LINK,capture_status,CAPTURE_STATUS\r\n" + Link(A) + ",,\r\n");
        Assert.Throws<InvalidDataException>(() => ReplayCatalog.Open(path));
    }

    [Fact]
    public void CatalogRefusesExternalEditWithoutOverwritingOrMarkingAttempt()
    {
        string path = Csv("REPLAY LINK\r\n" + Link(A) + "\r\n");
        using var catalog = ReplayCatalog.Open(path);
        File.AppendAllText(path, "external,edit\r\n");
        string edited = File.ReadAllText(path);
        Assert.Throws<IOException>(() => catalog.Mark(A, ReplayStatus.Done));
        Assert.Equal(edited, File.ReadAllText(path));
        Assert.Single(catalog.GetPending());
    }

    [Theory]
    [InlineData("https://share.polytopia.io.evil/g/eb7c997c-71e3-4eae-b973-08dd0c9ba532")]
    [InlineData("https://evil@share.polytopia.io/g/eb7c997c-71e3-4eae-b973-08dd0c9ba532")]
    [InlineData("https://share.polytopia.io/g/not-a-guid")]
    [InlineData("https://share.polytopia.io/g/00000000-0000-0000-0000-000000000000")]
    [InlineData("https://share.polytopia.io/g/eb7c997c-71e3-4eae-b973-08dd0c9ba532/extra")]
    public void CatalogRejectsInvalidLinks(string link) => Assert.False(ReplayCatalog.TryParseId(link, out _));

    [Fact]
    public void CatalogRejectsMalformedCsvAndReleasesItsLock()
    {
        string path = Csv("REPLAY LINK,notes\r\n\"unterminated");
        Assert.Throws<InvalidDataException>(() => ReplayCatalog.Open(path));
        File.WriteAllText(path, "REPLAY LINK\r\n" + Link(A) + "\r\n");
        using var catalog = ReplayCatalog.Open(path);
        Assert.Single(catalog.GetPending());
    }

    [Fact]
    public async Task SourceUsesFinalSnapshotAndFallbackAndKeepsBytesImmutable()
    {
        var handler = new Handler((request, number, token) => Task.FromResult(Json(number == 1 ? "{\"success\":false,\"errorMessage\":\"restricted\"}" : Envelope(Blob(123), 4))));
        using var client = new HttpClient(handler);
        using var source = new ReplaySource(client);
        var snapshot = await source.FetchAsync(A, "secret-test-token");
        Assert.Equal(A, snapshot.Id); Assert.Equal(123, snapshot.Version);
        byte[] altered = snapshot.Bytes; altered[0] = 0;
        Assert.Equal(Blob(123), snapshot.Bytes);
        Assert.Equal(64, snapshot.Sha256.Length);
        Assert.Equal(new[] { "get_game_view_model", "spectate_game" }, handler.Endpoints);
        Assert.All(handler.Bodies, body => Assert.Equal(A.ToString(), JsonDocument.Parse(body).RootElement.GetProperty("GameId").GetString()));
        Assert.All(handler.Auth, auth => Assert.Equal("Bearer secret-test-token", auth));
    }

    [Theory]
    [InlineData(401)]
    [InlineData(403)]
    [InlineData(500)]
    public async Task SourceHttpFailuresDoNotFallbackOrLeakServerBody(int status)
    {
        var handler = new Handler((r, n, t) => Task.FromResult(new HttpResponseMessage((HttpStatusCode)status) { Content = new StringContent("secret-test-token") }));
        using var client = new HttpClient(handler); using var source = new ReplaySource(client);
        Exception exception = await Assert.ThrowsAnyAsync<Exception>(() => source.FetchAsync(A, "secret-test-token"));
        Assert.DoesNotContain("secret-test-token", exception.ToString());
        if (status == 401) { Assert.IsType<UnauthorizedAccessException>(exception); Assert.Contains("Sign in", exception.Message); }
        else Assert.IsType<HttpRequestException>(exception);
        Assert.Single(handler.Endpoints);
    }

    [Theory]
    [InlineData("not-json")]
    [InlineData("{\"success\":true,\"data\":{\"state\":3,\"currentGameStateData\":\"AA==\"}}")]
    [InlineData("{\"success\":true,\"data\":{\"state\":\"4\",\"currentGameStateData\":\"AA==\"}}")]
    [InlineData("{\"success\":true,\"data\":{\"state\":4}}")]
    [InlineData("{\"success\":true,\"data\":{\"state\":4,\"currentGameStateData\":\"bad!\"}}")]
    [InlineData("{\"success\":true,\"data\":{\"state\":4,\"currentGameStateData\":\"AA==\"}}")]
    public async Task SourceRejectsMalformedAndUnfinishedSnapshots(string response)
    {
        var handler = new Handler((r, n, t) => Task.FromResult(Json(response)));
        using var client = new HttpClient(handler); using var source = new ReplaySource(client);
        await Assert.ThrowsAsync<InvalidDataException>(() => source.FetchAsync(A, "jwt"));
        Assert.Single(handler.Endpoints);
    }

    [Fact]
    public async Task SourceRejectsVersionMismatchButLeavesNativeCompatibilityToGame()
    {
        byte[] blob = Blob(123); BinaryPrimitives.WriteInt32LittleEndian(blob.AsSpan(4, 4), 124);
        var handler = new Handler((r, n, t) => Task.FromResult(Json(Envelope(blob))));
        using var client = new HttpClient(handler); using var source = new ReplaySource(client);
        await Assert.ThrowsAsync<InvalidDataException>(() => source.FetchAsync(A, "jwt"));
    }

    [Fact]
    public async Task SourceBoundsTimeoutAndHonorsCallerCancellation()
    {
        var handler = new Handler(async (r, n, token) => { await Task.Delay(Timeout.Infinite, token); return Json("{}"); });
        using var client = new HttpClient(handler); using var source = new ReplaySource(client, TimeSpan.FromMilliseconds(50));
        await Assert.ThrowsAsync<TimeoutException>(() => source.FetchAsync(A, "jwt"));
        using var cancellation = new CancellationTokenSource(); cancellation.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => source.FetchAsync(A, "jwt", cancellation.Token));
    }

    [Fact]
    public void OutputCommitRecoveryAndCsvRepairAreSeparateBoundaries()
    {
        string csv = Csv("REPLAY LINK\r\n" + Link(A) + "\r\n");
        var output = new ReplayOutput(Path.Combine(directory, "captures"));
        var attempt = output.Begin(A, 123, new string('a', 64));
        Assert.False(output.TryRecover(A, out _));
        Fill(attempt.DirectoryPath);
        var manifest = output.Commit(attempt, 11, new[] { 1, 7 });
        Assert.False(Directory.Exists(attempt.DirectoryPath));
        Assert.Equal(12, manifest.Artifacts.Length);
        Assert.Equal(4, manifest.Views.Length);
        Assert.Equal(new string('a', 64), manifest.SnapshotSha256);
        Assert.Equal(123, manifest.SerializationVersion);
        using (var catalog = ReplayCatalog.Open(csv)) Assert.Single(catalog.GetPending());
        var restarted = new ReplayOutput(Path.Combine(directory, "captures"));
        Assert.True(restarted.TryRecover(A, out var recovered));
        using (var catalog = ReplayCatalog.Open(csv)) catalog.Mark(A, ReplayStatus.Done, recovered!.DirectoryPath);
        using (var catalog = ReplayCatalog.Open(csv)) Assert.Empty(catalog.GetPending());
        Assert.Throws<IOException>(() => restarted.Begin(A, 123));
        File.AppendAllText(Path.Combine(manifest.DirectoryPath, "player-1-normal.grid.json"), " ");
        Assert.False(restarted.TryRecover(A, out _));
        var replacement = restarted.Begin(A, 123);
        string quarantined = Assert.Single(Directory.GetDirectories(Path.Combine(directory, "captures"), ".invalid-*"));
        Assert.True(File.Exists(Path.Combine(quarantined, "manifest.json")));
        Fill(replacement.DirectoryPath);
        restarted.Commit(replacement, 11, new[] { 1, 7 });
        Assert.True(restarted.TryRecover(A, out _));
    }

    [Theory]
    [InlineData("missing")]
    [InlineData("dimensions")]
    [InlineData("projection")]
    [InlineData("png-crc")]
    public void OutputRejectsIncompleteCorruptOrMismatchedArtifacts(string corruption)
    {
        var output = new ReplayOutput(Path.Combine(directory, "captures"));
        var attempt = output.Begin(A, 123); Fill(attempt.DirectoryPath);
        string prefix = Path.Combine(attempt.DirectoryPath, "player-1-normal");
        if (corruption == "missing") File.Delete(prefix + ".grid.png");
        if (corruption == "dimensions") File.WriteAllBytes(prefix + ".grid.png", Png(3, 2));
        if (corruption == "projection") File.WriteAllText(prefix + ".grid.json", "{\"size\":11,\"width\":2,\"height\":2,\"anchor\":[0,0],\"stepX\":[0,0],\"stepY\":[0,0]}");
        if (corruption == "png-crc") { byte[] bytes = File.ReadAllBytes(prefix + ".png"); bytes[30] ^= 1; File.WriteAllBytes(prefix + ".png", bytes); }
        Assert.ThrowsAny<Exception>(() => output.Commit(attempt, 11, new[] { 1, 7 }));
        Assert.False(output.TryRecover(A, out _));
        output.Abandon(attempt); Assert.False(Directory.Exists(attempt.DirectoryPath));
    }

    [Fact]
    public void OutputValidatesManifestIdentityAndForeignAttempts()
    {
        string root = Path.Combine(directory, "captures"); var output = new ReplayOutput(root);
        var attempt = output.Begin(A, 123); Fill(attempt.DirectoryPath);
        Assert.Throws<InvalidDataException>(() => output.Commit(attempt, 11, new[] { 1, 1 }));
        Assert.Throws<InvalidDataException>(() => output.Commit(attempt, 101, new[] { 1, 7 }));
        Assert.Throws<InvalidOperationException>(() => new ReplayOutput(root).Abandon(attempt));
        var manifest = output.Commit(attempt, 11, new[] { 1, 7 });
        manifest.Views[0] = "player-99-normal";
        File.WriteAllText(Path.Combine(manifest.DirectoryPath, "manifest.json"), JsonSerializer.Serialize(manifest));
        Assert.False(output.TryRecover(A, out _));
    }

    private static byte[] Blob(int version)
    {
        byte[] bytes = new byte[16]; BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(0, 4), version);
        BinaryPrimitives.WriteInt32LittleEndian(bytes.AsSpan(4, 4), version); bytes[8] = 17; return bytes;
    }
    private static string Envelope(byte[] bytes, int state = 4) => JsonSerializer.Serialize(new { success = true, data = new { state, currentGameStateData = Convert.ToBase64String(bytes), initialGameStateData = "not-used" } });
    private static HttpResponseMessage Json(string body) => new(HttpStatusCode.OK) { Content = new StringContent(body, Encoding.UTF8, "application/json") };
    private sealed class Handler : HttpMessageHandler
    {
        private readonly Func<HttpRequestMessage, int, CancellationToken, Task<HttpResponseMessage>> reply;
        public List<string> Endpoints { get; } = new();
        public List<string> Bodies { get; } = new();
        public List<string> Auth { get; } = new();
        public Handler(Func<HttpRequestMessage, int, CancellationToken, Task<HttpResponseMessage>> reply) { this.reply = reply; }
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Endpoints.Add(request.RequestUri!.Segments.Last()); Bodies.Add(await request.Content!.ReadAsStringAsync(cancellationToken));
            Auth.Add(request.Headers.Authorization!.ToString()); return await reply(request, Endpoints.Count, cancellationToken);
        }
    }
    private static void Fill(string directory)
    {
        foreach (int player in new[] { 1, 7 }) foreach (string mode in new[] { "normal", "revealed" })
        {
            string prefix = Path.Combine(directory, $"player-{player}-{mode}");
            File.WriteAllBytes(prefix + ".png", Png(2, 2)); File.WriteAllBytes(prefix + ".grid.png", Png(2, 2));
            File.WriteAllText(prefix + ".grid.json", "{\"size\":11,\"width\":2,\"height\":2,\"anchor\":[0,0],\"stepX\":[1,0],\"stepY\":[0,1]}");
        }
    }
    private static byte[] Png(int width, int height)
    {
        using var result = new MemoryStream(); result.Write(new byte[] { 137, 80, 78, 71, 13, 10, 26, 10 });
        byte[] header = new byte[13]; BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(0, 4), width); BinaryPrimitives.WriteInt32BigEndian(header.AsSpan(4, 4), height); header[8] = 8; header[9] = 2;
        Chunk("IHDR", header);
        using var packed = new MemoryStream();
        using (var zlib = new ZLibStream(packed, CompressionLevel.Fastest, true)) zlib.Write(new byte[(width * 3 + 1) * height]);
        Chunk("IDAT", packed.ToArray()); Chunk("IEND", Array.Empty<byte>()); return result.ToArray();
        void Chunk(string type, byte[] content)
        {
            byte[] length = new byte[4]; BinaryPrimitives.WriteInt32BigEndian(length, content.Length); result.Write(length);
            byte[] typed = Encoding.ASCII.GetBytes(type).Concat(content).ToArray(); result.Write(typed);
            uint crc = uint.MaxValue;
            foreach (byte b in typed) { crc ^= b; for (int i = 0; i < 8; i++) crc = (crc >> 1) ^ ((crc & 1) != 0 ? 0xedb88320u : 0u); }
            BinaryPrimitives.WriteUInt32BigEndian(length, ~crc); result.Write(length);
        }
    }
}
