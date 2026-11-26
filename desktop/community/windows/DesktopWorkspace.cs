using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

// WebView2 local storage is scoped to the port. Keep workspace state in the
// WebView profile, partitioned by the actual library directory.
internal sealed class DesktopWorkspace
{
    private readonly string path;
    private readonly JavaScriptSerializer json = new JavaScriptSerializer();

    internal DesktopWorkspace(string profile, string libraryPath)
    {
        using (var hash = SHA256.Create()) {
            byte[] digest = hash.ComputeHash(Encoding.UTF8.GetBytes(libraryPath.ToUpperInvariant()));
            path = Path.Combine(profile, "RunTeams-Workspace", BitConverter.ToString(digest).Replace("-", "") + ".json");
        }
    }

    internal object Handle(string[] fields)
    {
        Guid library, generation;
        if (fields.Length < 5 || !Guid.TryParseExact(fields[3], "D", out library) ||
            !Guid.TryParseExact(fields[4], "D", out generation)) throw new ArgumentException();
        string scope = library.ToString("D") + "/" + generation.ToString("D");
        if (fields[2] == "workspace-boards-read" || fields[2] == "workspace-board-write")
            return Boards(fields, scope);
        if (fields[2] == "workspace-drafts-read" || fields[2] == "workspace-drafts-write")
            return Drafts(fields, scope);
        if (fields[2] == "workspace-read" && fields.Length == 5) {
            string windows = null;
            if (File.Exists(path)) {
                var record = json.Deserialize<Dictionary<string, string>>(File.ReadAllText(path, Encoding.UTF8));
                windows = record["scope"] == scope ? record["windows"] : "[]";
            }
            return new { windows };
        }
        if (fields[2] != "workspace-write" || fields.Length != 6 ||
            !(json.DeserializeObject(fields[5]) is object[])) throw new ArgumentException();
        string recordText = json.Serialize(new { scope, windows = fields[5] });
        WriteAtomic(path, recordText);
        return new { saved = true };
    }

    private object Drafts(string[] fields, string scope)
    {
        string file = Path.ChangeExtension(path, ".drafts.json");
        if (fields[2] == "workspace-drafts-read" && fields.Length == 5) {
            string drafts = null;
            if (File.Exists(file)) {
                var record = json.Deserialize<Dictionary<string, string>>(File.ReadAllText(file, Encoding.UTF8));
                drafts = record["scope"] == scope ? record["drafts"] : "{}";
            }
            return new { drafts };
        }
        if (fields[2] != "workspace-drafts-write" || fields.Length != 6 ||
            !(json.DeserializeObject(fields[5]) is Dictionary<string, object>)) throw new ArgumentException();
        WriteAtomic(file, json.Serialize(new { scope, drafts = fields[5] }));
        return new { saved = true };
    }

    private object Boards(string[] fields, string scope)
    {
        string file = Path.ChangeExtension(path, ".boards.json");
        var boards = File.Exists(file)
            ? json.Deserialize<Dictionary<string, string>>(File.ReadAllText(file, Encoding.UTF8))
            : new Dictionary<string, string>();
        string prior;
        if (!boards.TryGetValue("scope", out prior) || prior != scope) boards.Clear();
        if (fields[2] == "workspace-boards-read" && fields.Length == 5) {
            boards.Remove("scope");
            return new { boards };
        }
        if (fields[2] != "workspace-board-write" || fields.Length != 6) throw new ArgumentException();
        var update = json.Deserialize<Dictionary<string, string>>(fields[5]);
        string key = update["key"], value = update["value"];
        if (!key.StartsWith("runteams.pipeline-board:", StringComparison.Ordinal) ||
            !(json.DeserializeObject(value) is Dictionary<string, object>)) throw new ArgumentException();
        boards["scope"] = scope;
        boards[key] = value;
        WriteAtomic(file, json.Serialize(boards));
        return new { saved = true };
    }

    private static void WriteAtomic(string path, string recordText)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try {
            File.WriteAllText(temporary, recordText, Encoding.UTF8);
            if (File.Exists(path)) File.Replace(temporary, path, null);
            else File.Move(temporary, path);
        } finally { File.Delete(temporary); }
    }
}
