using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

internal sealed class DesktopSettings : IDisposable
{
    private const string Preferences = @"Software\RunTeams.ai\Local\Desktop";
    private const string Startup = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string StartupName = "RunTeams.Local";
    private readonly Timer timer = new Timer { Interval = 2000 };
    private readonly HttpClient service;
    private bool reading, disposed, sleepHeld;
    private string powerError;

    internal DesktopSettings(Uri origin, string token)
    {
        service = new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false });
        service.BaseAddress = origin;
        service.Timeout = TimeSpan.FromSeconds(5);
        service.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", token);
        timer.Tick += async delegate {
            if (reading || disposed) return;
            reading = true;
            try {
                bool active = PreventSleep && await service.GetStringAsync("/api/desktop/work-active") == "true";
                if (!disposed) UpdatePower(active && PreventSleep);
            } catch (Exception) {
                if (!disposed) {
                    UpdatePower(false);
                    powerError = "Could not read the local work status.";
                }
            } finally { reading = false; }
        };
        timer.Start();
    }

    private static object Read(string key, string name)
    {
        using (var registry = Registry.CurrentUser.OpenSubKey(key))
            return registry == null ? null : registry.GetValue(name);
    }
    private static bool PreventSleep { get { return Equals(Read(Preferences, "prevent_sleep"), 1); } }
    internal static bool KeepInBackground
    {
        get {
            try { return Equals(Read(Preferences, "close_action"), "background"); }
            catch (System.Security.SecurityException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
            catch (System.IO.IOException) { return false; }
        }
    }
    private static string LaunchCommand { get { return "\"" + Application.ExecutablePath + "\""; } }
    private static bool LaunchAtLogin
    {
        get { return String.Equals(Read(Startup, StartupName) as string, LaunchCommand, StringComparison.OrdinalIgnoreCase); }
    }

    private static readonly string[] AppearanceKeys = { "theme", "interface_font_size", "code_font_size", "restore_windows" };

    private static bool ValidLanguage(string value)
    {
        return value == "system" || value == "zh-CN" || value == "en";
    }

    internal static string SavedLanguage
    {
        get {
            try {
                string value = Read(Preferences, "language") as string;
                return ValidLanguage(value) ? value : null;
            }
            catch (System.Security.SecurityException) { return null; }
            catch (UnauthorizedAccessException) { return null; }
            catch (System.IO.IOException) { return null; }
        }
    }

    private static object AppearanceValue(string key, string value)
    {
        if (key == "theme" && (value == "light" || value == "dark" || value == "system")) return value;
        if (key == "restore_windows" && (value == "true" || value == "false")) return value == "true";
        if (key == "code_font_size" && value == "11") return 11;
        if ((key == "interface_font_size" || key == "code_font_size") &&
            (value == "12" || value == "13" || value == "14" || value == "16" || value == "18"))
            return int.Parse(value, System.Globalization.CultureInfo.InvariantCulture);
        return null;
    }

    private static Dictionary<string, object> ReadAppearance()
    {
        var values = new Dictionary<string, object>();
        using (var prefs = Registry.CurrentUser.OpenSubKey(Preferences)) {
            if (prefs != null) foreach (string key in AppearanceKeys) {
                object value = AppearanceValue(key, prefs.GetValue(key) as string);
                if (value != null) values[key] = value;
            }
        }
        return values;
    }

    internal object Settings(string[] fields)
    {
        if (fields.Length == 5 && fields[2] == "set") {
            string key = fields[3], value = fields[4];
            if (key == "launch_at_login" && (value == "true" || value == "false")) {
                using (var run = Registry.CurrentUser.CreateSubKey(Startup)) {
                    if (value == "true") run.SetValue(StartupName, LaunchCommand, RegistryValueKind.String);
                    else if (LaunchAtLogin) run.DeleteValue(StartupName, false);
                }
            } else if (key == "prevent_sleep" && (value == "true" || value == "false")) {
                using (var prefs = Registry.CurrentUser.CreateSubKey(Preferences))
                    prefs.SetValue(key, value == "true" ? 1 : 0, RegistryValueKind.DWord);
                if (value == "false") UpdatePower(false);
            } else if ((key == "close_action" && (value == "background" || value == "quit")) ||
                       (key == "language" && ValidLanguage(value)) || AppearanceValue(key, value) != null) {
                using (var prefs = Registry.CurrentUser.CreateSubKey(Preferences)) prefs.SetValue(key, value);
            } else throw new ArgumentException("Invalid desktop preference.");
        } else if (fields.Length != 3 || fields[2] != "get") throw new ArgumentException("Invalid settings request.");
        return new { language = SavedLanguage, launch_at_login = LaunchAtLogin, prevent_sleep = PreventSleep,
                     close_action = KeepInBackground ? "background" : "quit", runtime_error = powerError,
                     appearance = ReadAppearance() };
    }

    [DllImport("kernel32.dll")] private static extern uint SetThreadExecutionState(uint flags);
    private void UpdatePower(bool hold)
    {
        // WinForms timer continuations run on the window thread that owns this request.
        const uint continuous = 0x80000000, systemRequired = 1;
        if (hold != sleepHeld && SetThreadExecutionState(hold ? continuous | systemRequired : continuous) == 0) {
            powerError = "Windows could not update the sleep request.";
            return;
        }
        sleepHeld = hold;
        powerError = null;
    }
    public void Dispose()
    {
        disposed = true;
        timer.Dispose();
        UpdatePower(false);
        service.Dispose();
    }
}
