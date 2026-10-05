using System.Security.Cryptography;
using System.Text;

namespace BoardCaptureLoop;

public static class ReplayStatus
{
    public const string Done = "done";
    public const string SkippedNonTwoPlayer = "skipped_non_two_player";
    public const string RetryableError = "retryable_error";
}

public sealed class ReplayEntry
{
    public Guid Id { get; }
    public string Link { get; }
    internal ReplayEntry(Guid id) { Id = id; Link = "https://share.polytopia.io/g/" + id.ToString("D"); }
}

/// <summary>One runtime CSV writer. Opening never modifies the input; Mark commits a whole-file replacement.</summary>
public sealed class ReplayCatalog : IDisposable
{
    private readonly string path;
    private readonly FileStream writerLock;
    private readonly List<List<string>> rows;
    private readonly List<ReplayEntry> entries = new();
    private readonly Dictionary<Guid, List<int>> rowIds = new();
    private readonly HashSet<Guid> attempted = new();
    private readonly int statusColumn, outputColumn, errorColumn;
    private readonly bool bom;
    private byte[] diskHash;
    private bool disposed;

    private ReplayCatalog(string csvPath)
    {
        path = Path.GetFullPath(csvPath);
        writerLock = new FileStream(path + ".lock", FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None);
        try
        {
            byte[] bytes = File.ReadAllBytes(path);
            diskHash = SHA256.HashData(bytes);
            bom = bytes.Length >= 3 && bytes[0] == 239 && bytes[1] == 187 && bytes[2] == 191;
            string text = new UTF8Encoding(false, true).GetString(bytes, bom ? 3 : 0, bytes.Length - (bom ? 3 : 0));
            rows = Parse(text);
            if (rows.Count == 0) throw new InvalidDataException("Replay CSV has no header.");
            foreach (string name in new[] { "REPLAY LINK", "capture_status", "capture_output", "capture_error" })
                if (rows[0].Count(h => string.Equals(h.Trim(), name, StringComparison.OrdinalIgnoreCase)) > 1)
                    throw new InvalidDataException("Replay CSV contains duplicate " + name + " columns.");
            int linkColumn = rows[0].FindIndex(h => string.Equals(h.Trim(), "REPLAY LINK", StringComparison.OrdinalIgnoreCase));
            if (linkColumn < 0) throw new InvalidDataException("Replay CSV requires a REPLAY LINK column.");
            statusColumn = Column("capture_status");
            outputColumn = Column("capture_output");
            errorColumn = Column("capture_error");
            for (int i = 1; i < rows.Count; i++)
            {
                while (rows[i].Count < rows[0].Count) rows[i].Add("");
                if (linkColumn >= rows[i].Count || !TryParseId(rows[i][linkColumn], out Guid id)) continue;
                if (!rowIds.TryGetValue(id, out var indices))
                {
                    indices = new List<int>(); rowIds.Add(id, indices); entries.Add(new ReplayEntry(id));
                }
                indices.Add(i);
            }
        }
        catch { writerLock.Dispose(); throw; }
    }

    public static ReplayCatalog Open(string csvPath) => new(csvPath);

    public IReadOnlyList<ReplayEntry> GetPending()
    {
        ThrowIfDisposed();
        return entries.Where(e => !attempted.Contains(e.Id) && !rowIds[e.Id].Any(i =>
            rows[i][statusColumn] == ReplayStatus.Done || rows[i][statusColumn] == ReplayStatus.SkippedNonTwoPlayer)).ToArray();
    }

    public IReadOnlyList<ReplayEntry> GetCompleted()
    {
        ThrowIfDisposed();
        return entries.Where(e => rowIds[e.Id].Any(i => rows[i][statusColumn] == ReplayStatus.Done)).ToArray();
    }

    public void Mark(Guid id, string status, string? output = null, string? error = null)
    {
        ThrowIfDisposed();
        if (status != ReplayStatus.Done && status != ReplayStatus.SkippedNonTwoPlayer && status != ReplayStatus.RetryableError)
            throw new ArgumentException("Unknown replay status.", nameof(status));
        if (!rowIds.TryGetValue(id, out var indices)) throw new ArgumentException("Replay is not in this catalog.", nameof(id));
        byte[] current = File.ReadAllBytes(path);
        if (!diskHash.SequenceEqual(SHA256.HashData(current)))
            throw new IOException("Replay CSV changed outside this capture run; refusing to overwrite it. Reopen the catalog.");
        bool wasCompleted = indices.Any(index => rows[index][statusColumn] == ReplayStatus.Done);
        var updated = rows.Select(r => new List<string>(r)).ToList();
        foreach (int index in indices)
        {
            updated[index][statusColumn] = status;
            updated[index][outputColumn] = output ?? "";
            updated[index][errorColumn] = error ?? "";
        }
        byte[] bytes = new UTF8Encoding(bom).GetBytes(Serialize(updated));
        if (bom) bytes = new byte[] { 239, 187, 191 }.Concat(bytes).ToArray();
        string temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
        try
        {
            using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
            { stream.Write(bytes, 0, bytes.Length); stream.Flush(true); }
            if (!diskHash.SequenceEqual(SHA256.HashData(File.ReadAllBytes(path))))
                throw new IOException("Replay CSV changed during update; refusing to overwrite it.");
            File.Replace(temporary, path, path + ".bak", true);
            diskHash = SHA256.HashData(bytes);
            rows.Clear(); rows.AddRange(updated);
            if (status == ReplayStatus.RetryableError && wasCompleted) attempted.Remove(id);
            else attempted.Add(id);
        }
        finally { if (File.Exists(temporary)) File.Delete(temporary); }
    }

    public static bool TryParseId(string link, out Guid id)
    {
        id = default;
        if (!Uri.TryCreate(link.Trim(), UriKind.Absolute, out var uri) ||
            (uri.Scheme != "https" && uri.Scheme != "http") ||
            !string.Equals(uri.Host, "share.polytopia.io", StringComparison.OrdinalIgnoreCase) ||
            !uri.IsDefaultPort || !string.IsNullOrEmpty(uri.UserInfo)) return false;
        string[] segments = uri.AbsolutePath.Trim('/').Split('/');
        return segments.Length == 2 && segments[0] == "g" && Guid.TryParseExact(segments[1], "D", out id) && id != Guid.Empty;
    }

    private int Column(string name)
    {
        int index = rows[0].FindIndex(h => string.Equals(h.Trim(), name, StringComparison.OrdinalIgnoreCase));
        if (index < 0) { index = rows[0].Count; rows[0].Add(name); }
        return index;
    }

    private static List<List<string>> Parse(string text)
    {
        var result = new List<List<string>>();
        var row = new List<string>(); var field = new StringBuilder();
        bool quoted = false, closed = false, started = false;
        for (int i = 0; i < text.Length; i++)
        {
            char c = text[i];
            if (quoted)
            {
                if (c == '"')
                {
                    if (i + 1 < text.Length && text[i + 1] == '"') { field.Append('"'); i++; }
                    else { quoted = false; closed = true; }
                }
                else field.Append(c);
                continue;
            }
            if (c == ',' || c == '\r' || c == '\n')
            {
                row.Add(field.ToString()); field.Clear(); closed = false; started = false;
                if (c != ',')
                {
                    result.Add(row); row = new List<string>();
                    if (c == '\r' && i + 1 < text.Length && text[i + 1] == '\n') i++;
                }
            }
            else if (c == '"' && !started && !closed) { quoted = true; started = true; }
            else
            {
                if (closed || c == '"') throw new InvalidDataException("Malformed quoted CSV field.");
                field.Append(c); started = true;
            }
        }
        if (quoted) throw new InvalidDataException("Unterminated quoted CSV field.");
        if (field.Length > 0 || row.Count > 0 || started || closed) { row.Add(field.ToString()); result.Add(row); }
        return result;
    }

    private static string Serialize(IEnumerable<List<string>> records) => string.Join("\r\n", records.Select(row =>
        string.Join(",", row.Select(value => value.IndexOfAny(new[] { ',', '"', '\r', '\n' }) >= 0
            ? "\"" + value.Replace("\"", "\"\"") + "\"" : value)))) + "\r\n";
    private void ThrowIfDisposed() { if (disposed) throw new ObjectDisposedException(nameof(ReplayCatalog)); }
    public void Dispose() { if (!disposed) { disposed = true; writerLock.Dispose(); } }
}
