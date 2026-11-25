using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;

// WebView2 local storage is scoped to the port. Keep tab metadata in the
// WebView profile and partition it by the actual library directory.
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
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        string temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try {
            File.WriteAllText(temporary, recordText, Encoding.UTF8);
            if (File.Exists(path)) File.Replace(temporary, path, null);
            else File.Move(temporary, path);
        } finally { File.Delete(temporary); }
        return new { saved = true };
    }
}
