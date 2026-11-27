using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Http;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal sealed class LocalWindow : Form
{
    private readonly WebView2 view = new WebView2();
    private readonly Process service = new Process();
    private readonly HashSet<CoreWebView2DownloadOperation> downloads = new HashSet<CoreWebView2DownloadOperation>();
    private bool started, closing, checkingClose, loaded;
    private Uri origin;
    private int navigationVersion;
    private DesktopSettings settings;
    private DesktopWorkspace workspace;
    private DesktopNotifications notifications;
    private readonly ContextMenuStrip trayMenu = new ContextMenuStrip();
    private readonly NotifyIcon tray = new NotifyIcon();
    private readonly Timer notificationTimer = new Timer { Interval = 5000 };
    private bool notificationPermission, updatingNotificationPermission;
    private bool quitRequested;

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--open-notification") return DesktopNotifications.OpenNotification(args);
        if (args.Length > 0 && args[0] == "--picker") return AttachmentPicker.Run(args);
        if (args.Length > 0 && args[0] == "--sdk")
        {
            try { return RunSdk(args); }
            catch (Exception error) { Console.Error.WriteLine(error.Message); return 2; }
        }
        Application.EnableVisualStyles();
        DesktopNotifications.SetCurrentProcessExplicitAppUserModelID(DesktopNotifications.AppId);
        try
        {
            using (var window = new LocalWindow(args)) {
                string identity = System.Security.Principal.WindowsIdentity.GetCurrent().User.Value + "|" + window.libraryPath.ToUpperInvariant();
                byte[] digest;
                using (var sha = System.Security.Cryptography.SHA256.Create()) digest = sha.ComputeHash(Encoding.UTF8.GetBytes(identity));
                bool first;
                using (var reopen = new System.Threading.EventWaitHandle(false, System.Threading.EventResetMode.AutoReset,
                        @"Local\RunTeams.Local." + BitConverter.ToString(digest), out first)) {
                    if (!first) {
                        if (Array.IndexOf(args, "--port") >= 0) throw new IOException("This library is already open.");
                        reopen.Set();
                        return 0;
                    }
                    // Create the UI handle before another launcher signals the window.
                    IntPtr handle = window.Handle;
                    var listener = System.Threading.ThreadPool.RegisterWaitForSingleObject(reopen, delegate {
                        try { window.BeginInvoke((Action)window.RestoreWindow); }
                        catch (InvalidOperationException) { }
                    }, null, -1, false);
                    try { Application.Run(window); }
                    finally { listener.Unregister(null); }
                }
            }
            return Environment.ExitCode;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "RunTeams Local", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static readonly string Core = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "core");

    private static ProcessStartInfo Python()
    {
        string tools = Path.Combine(Core, "runtime-dependencies");
        var start = new ProcessStartInfo {
            FileName = Path.Combine(tools, @"agent-python\python.exe"),
            UseShellExecute = false, CreateNoWindow = true
        };
        start.EnvironmentVariables["RUNTEAMS_MCP_RUNTIME_DIR"] = Path.Combine(tools, "mcp-runtime");
        start.EnvironmentVariables["RUNTEAMS_CREATOR_BUILDER_DIR"] = Path.Combine(tools, "creator-builder");
        return start;
    }

    // .NET Framework exposes a single command line. Preserve quotes and trailing
    // backslashes using the Windows C runtime's argv escaping rules.
    private static string QuoteArgument(string value)
    {
        var quoted = new StringBuilder("\"");
        int slashes = 0;
        foreach (char c in value) {
            if (c == '\\') { slashes++; continue; }
            quoted.Append('\\', c == '"' ? 2 * slashes + 1 : slashes);
            quoted.Append(c);
            slashes = 0;
        }
        return quoted.Append('\\', 2 * slashes).Append('"').ToString();
    }

    private static int RunSdk(string[] args)
    {
        var start = Python();
        const string entry = "import sys;from runteams_creator_dev.cli import main;raise SystemExit(main(sys.argv[1:],packaged=True))";
        var arguments = new StringBuilder("-I -B -X utf8 -u -c ").Append(QuoteArgument(entry));
        for (int i = 1; i < args.Length; i++) arguments.Append(' ').Append(QuoteArgument(args[i]));
        start.Arguments = arguments.ToString();
        start.RedirectStandardOutput = start.RedirectStandardError = true;
        // A GUI-subsystem executable launched interactively has no console.
        // Preserve inherited pipe handles when a caller captures SDK output.
        if (GetStdHandle(-11) == IntPtr.Zero) AttachConsole(0xffffffff);
        using (var sdk = Process.Start(start)) {
            Task stdout = sdk.StandardOutput.BaseStream.CopyToAsync(Console.OpenStandardOutput());
            Task stderr = sdk.StandardError.BaseStream.CopyToAsync(Console.OpenStandardError());
            Task.WaitAll(stdout, stderr);
            sdk.WaitForExit();
            return sdk.ExitCode;
        }
    }

    [DllImport("kernel32.dll")] private static extern IntPtr GetStdHandle(int handle);
    [DllImport("kernel32.dll")] private static extern bool AttachConsole(uint processId);

    private readonly string libraryPath;
    private void RestoreWindow()
    {
        if (closing || IsDisposed) return;
        Show();
        if (WindowState == FormWindowState.Minimized) WindowState = FormWindowState.Normal;
        Activate();
        tray.Visible = false;
    }

    private LocalWindow(string[] args)
    {
        Text = "RunTeams Local";
        ClientSize = new Size(1120, 760);
        MinimumSize = new Size(780, 560);
        StartPosition = FormStartPosition.CenterScreen;
        view.Dock = DockStyle.Fill;
        Controls.Add(view);

        int port = 0;
        string data = Environment.GetEnvironmentVariable("RUNTEAMS_DATA");
        for (int i = 0; i < args.Length; i += 2)
        {
            if (i + 1 >= args.Length) throw new ArgumentException("Missing option value.");
            if (args[i] == "--data-dir") data = Path.GetFullPath(args[i + 1]);
            else if (args[i] != "--port" || !int.TryParse(args[i + 1], out port) || port < 0 || port > 65535)
                throw new ArgumentException("Expected --data-dir PATH or --port 0..65535.");
        }
        service.StartInfo = Python();
        libraryPath = Path.GetFullPath(String.IsNullOrEmpty(data)
            ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData), @"RunTeams.ai\community") : data).TrimEnd('\\', '/');
        bool chinese = System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "zh";
        trayMenu.Items.Add(chinese ? "打开 RunTeams" : "Open RunTeams", null, delegate { RestoreWindow(); });
        trayMenu.Items.Add(chinese ? "退出" : "Quit", null, delegate {
            RestoreWindow();
            quitRequested = true;
            Close();
        });
        tray.Icon = Icon;
        tray.Text = Text;
        tray.ContextMenuStrip = trayMenu;
        tray.DoubleClick += delegate { RestoreWindow(); };
        Disposed += delegate {
            notificationTimer.Dispose();
            tray.Dispose();
            trayMenu.Dispose();
            if (settings != null) settings.Dispose();
        };
        service.StartInfo.EnvironmentVariables["RUNTEAMS_ATTACHMENT_PICKER"] = Application.ExecutablePath;
        service.StartInfo.Arguments = "-I -B -X utf8 -u -m runteams_core.application.community --owner-stdin --port " + port;
        service.StartInfo.WorkingDirectory = Core;
        service.StartInfo.RedirectStandardInput = service.StartInfo.RedirectStandardOutput = service.StartInfo.RedirectStandardError = true;
        service.StartInfo.StandardOutputEncoding = service.StartInfo.StandardErrorEncoding = Encoding.UTF8;
        if (!string.IsNullOrEmpty(data)) service.StartInfo.EnvironmentVariables["RUNTEAMS_DATA"] = data;
        Shown += async delegate { await StartService(); };
        FormClosing += OnClosing;
        FormClosed += delegate {
            if (started) service.StandardInput.Close();
            service.Dispose();
        };
    }

    private async Task StartService()
    {
        try
        {
            service.Start();
            started = true;
            string lastError = null;
            service.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) {
                if (!string.IsNullOrWhiteSpace(e.Data)) lastError = e.Data;
            };
            service.BeginErrorReadLine();
            Task<string> descriptor = service.StandardOutput.ReadLineAsync();
            if (await Task.WhenAny(descriptor, Task.Delay(60000)) != descriptor)
                throw new TimeoutException("The local library did not open within one minute.");
            string line = await descriptor;
            if (line == null) {
                service.WaitForExit();
                throw new IOException("Could not open the local library.\n" + lastError);
            }
            if (IsDisposed || closing) return;
            var info = new JavaScriptSerializer().Deserialize<System.Collections.Generic.Dictionary<string, object>>(line);
            origin = new Uri((string)info["origin"]);
            if ((string)info["schema"] != "runteams.local-service/1" || (string)info["edition"] != "community"
                || origin.Scheme != "http" || origin.Host != "127.0.0.1" || origin.Port <= 0
                || origin.PathAndQuery != "/" || origin.UserInfo != "" || origin.Fragment != "")
                throw new InvalidDataException("Invalid local service address.");

            string profile = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                          "RunTeams.ai", "Local", "WebView2");
            var environment = await CoreWebView2Environment.CreateAsync(null, profile);
            if (IsDisposed || closing) return;
            await view.EnsureCoreWebView2Async(environment);
            var browser = view.CoreWebView2;
            try { browser.DownloadStarting += TrackDownload; }
            catch (NotImplementedException) { /* Older runtimes can still open the library. */ }
            browser.Settings.AreHostObjectsAllowed = false;
            // Receive DOM File handles from the top-level WebView only. The service
            // credential stays in this process and is never injected into the page.
            string sessionToken = (string)info["session_token"];
            settings = new DesktopSettings(origin, sessionToken);
            workspace = new DesktopWorkspace(environment.UserDataFolder, libraryPath);
            // WebView2 permissions belong to an origin. The service port changes on restart.
            try {
                notifications = new DesktopNotifications(this, RestoreWindow, delegate(bool success) {
                    if (!closing && !IsDisposed && browser.Source.StartsWith(origin.AbsoluteUri, StringComparison.Ordinal))
                        browser.PostWebMessageAsJson(success ? "{\"kind\":\"work-alert-delivery\",\"ok\":true}"
                                                             : "{\"kind\":\"work-alert-delivery\",\"ok\":false}");
                });
                browser.NotificationReceived += delegate(object sender, CoreWebView2NotificationReceivedEventArgs e) {
                    e.Handled = true;
                    if (!closing && e.SenderOrigin.TrimEnd('/') == origin.GetLeftPart(UriPartial.Authority)
                        && DesktopSettings.NotificationsEnabled) notifications.Show(e.Notification);
                };
                await SetNotificationPermission(browser, DesktopSettings.NotificationsEnabled);
                // A hidden WebView throttles JavaScript timers. Wake the library from the window thread.
                notificationTimer.Tick += async delegate {
                    if (!loaded || closing || updatingNotificationPermission) return;
                    bool enabled = DesktopSettings.NotificationsEnabled;
                    if (enabled != notificationPermission) {
                        try { await SetNotificationPermission(browser, enabled); }
                        catch (InvalidOperationException) { return; }
                        if (closing || IsDisposed) return;
                    }
                    if (!enabled) return;
                    bool foreground = Visible && WindowState != FormWindowState.Minimized && ActiveForm == this;
                    browser.PostWebMessageAsJson(foreground ? "{\"kind\":\"work-alerts\",\"foreground\":true}"
                                                            : "{\"kind\":\"work-alerts\",\"foreground\":false}");
                };
                notificationTimer.Start();
            } catch (NotImplementedException) { /* Older runtimes can still open the library. */ }
            // Supply the saved language before the first page parses its locale scripts.
            string languageScript = null;
            string language = DesktopSettings.SavedLanguage;
            if (language != null) {
                var json = new JavaScriptSerializer();
                languageScript = await browser.AddScriptToExecuteOnDocumentCreatedAsync(
                    "if (window === window.top && location.origin === " + json.Serialize(origin.GetLeftPart(UriPartial.Authority)) + ") {" +
                    "window.runteamsNativeLanguage = " + json.Serialize(language) + ";" +
                    "try { localStorage.setItem('runteams_language_preference', window.runteamsNativeLanguage); } catch {} }");
            }
            browser.WebMessageReceived += async (sender, e) => await HandleWebMessage(browser, e, sessionToken);
            browser.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) {
                Uri destination;
                e.Cancel = !Uri.TryCreate(e.Uri, UriKind.Absolute, out destination)
                    || destination.GetLeftPart(UriPartial.Authority) != origin.GetLeftPart(UriPartial.Authority);
                if (!e.Cancel) {
                    if (notifications != null) notifications.Dispose();
                    navigationVersion++;
                }
            };
            browser.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) {
                e.Handled = true;
                Uri url;
                if (e.IsUserInitiated && Uri.TryCreate(e.Uri, UriKind.Absolute, out url)
                    && (url.Scheme == "https" || url.Scheme == "http"))
                    Process.Start(new ProcessStartInfo(url.AbsoluteUri) { UseShellExecute = true });
            };
            browser.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                if (e.IsSuccess) {
                    loaded = true;
                    if (languageScript != null && browser.Source.StartsWith(origin.AbsoluteUri, StringComparison.Ordinal)) {
                        browser.RemoveScriptToExecuteOnDocumentCreated(languageScript);
                        languageScript = null;
                    }
                }
            };
            service.EnableRaisingEvents = true;
            service.Exited += delegate {
                if (!IsDisposed && IsHandleCreated) BeginInvoke((Action)delegate {
                    if (!closing) Fail("The local service stopped. Reopen RunTeams Local to continue.");
                });
            };
            if (service.HasExited) throw new IOException("The local service stopped during startup.");
            browser.Navigate(origin.AbsoluteUri);
        }
        catch (WebView2RuntimeNotFoundException) {
            if (!closing && !IsDisposed) Fail("Install Microsoft Edge WebView2 Evergreen Runtime, then reopen RunTeams Local.");
        }
        catch (Exception error) { if (!closing && !IsDisposed) Fail(error.Message); }
    }

    private async Task HandleWebMessage(CoreWebView2 browser, CoreWebView2WebMessageReceivedEventArgs e, string sessionToken)
    {
        Uri source;
        if (!Uri.TryCreate(e.Source, UriKind.Absolute, out source) ||
            source.GetLeftPart(UriPartial.Authority) != origin.GetLeftPart(UriPartial.Authority)) return;
        int version = navigationVersion;
        string id = null;
        object result = null;
        var json = new JavaScriptSerializer();
        try {
            string[] fields = e.TryGetWebMessageAsString().Split(new[] { ':' }, 6);
            Guid parsed;
            if (fields.Length >= 2 && fields[0] == "desktop-settings" && Guid.TryParseExact(fields[1], "D", out parsed)) {
                object value = null;
                try {
                    if (fields.Length == 3 && (fields[2] == "notifications-enable" || fields[2] == "notifications-disable")) {
                        bool enabled = fields[2] == "notifications-enable";
                        if (!notificationTimer.Enabled || updatingNotificationPermission) throw new InvalidOperationException();
                        await SetNotificationPermission(browser, enabled);
                        DesktopSettings.NotificationsEnabled = enabled;
                        if (!enabled && notifications != null) notifications.Dispose();
                        value = new { enabled = enabled };
                    } else if (fields.Length == 3 && fields[2] == "notifications-settings") {
                        Process.Start(new ProcessStartInfo("ms-settings:notifications") { UseShellExecute = true });
                        value = new { ok = true };
                    } else if (fields.Length == 3 && fields[2] == "notifications-activate") {
                        RestoreWindow();
                        value = new { ok = true };
                    } else value = fields.Length >= 3 && fields[2].StartsWith("workspace-", StringComparison.Ordinal)
                        ? workspace.Handle(fields) : settings.Settings(fields);
                }
                catch (Exception) { /* The web settings page offers a readback and retry. */ }
                browser.PostWebMessageAsJson(json.Serialize(new { kind = "desktop-settings", id = fields[1], result = value }));
                return;
            }
            if (fields.Length != 4 || fields[0] != "reference-drop" ||
                !Guid.TryParseExact(fields[1], "D", out parsed) || !Guid.TryParseExact(fields[2], "D", out parsed) ||
                !Guid.TryParseExact(fields[3], "D", out parsed)) return;
            id = fields[1];
            var files = e.AdditionalObjects;
            if (files == null || files.Count < 1 || files.Count > 10) throw new InvalidDataException();
            var paths = new System.Collections.Generic.List<string>();
            foreach (var item in files) {
                var file = item as CoreWebView2File;
                if (file == null || String.IsNullOrEmpty(file.Path) || !Path.IsPathRooted(file.Path))
                    throw new InvalidDataException();
                paths.Add(file.Path);
            }
            using (var client = new HttpClient(new HttpClientHandler { UseProxy = false, AllowAutoRedirect = false }))
            using (var request = new HttpRequestMessage(HttpMethod.Post, new Uri(origin, "/api/local-references/drop"))) {
                // Each of up to ten selected Git repositories may need local metadata checks.
                client.Timeout = TimeSpan.FromMinutes(6);
                request.Headers.ExpectContinue = false;
                request.Headers.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", sessionToken);
                request.Headers.Add("X-RunTeams-Library", fields[2]);
                request.Headers.Add("X-RunTeams-Library-Generation", fields[3]);
                request.Content = new StringContent(json.Serialize(new { paths }), Encoding.UTF8, "application/json");
                using (var response = await client.SendAsync(request)) {
                    if (response.IsSuccessStatusCode)
                        result = json.DeserializeObject(await response.Content.ReadAsStringAsync());
                }
            }
        } catch (Exception) {
            // Invalid or unavailable OS-backed objects get the normal picker fallback.
        }
        if (id != null && version == navigationVersion && !closing && !IsDisposed && !view.IsDisposed)
            browser.PostWebMessageAsJson(json.Serialize(new { kind = "reference-drop", id, result }));
    }

    private async Task SetNotificationPermission(CoreWebView2 browser, bool enabled)
    {
        updatingNotificationPermission = true;
        try {
            await browser.Profile.SetPermissionStateAsync(CoreWebView2PermissionKind.Notifications,
                origin.GetLeftPart(UriPartial.Authority), enabled ? CoreWebView2PermissionState.Allow : CoreWebView2PermissionState.Default);
            notificationPermission = enabled;
        } finally { updatingNotificationPermission = false; }
    }

    private void Fail(string message)
    {
        closing = true;
        Environment.ExitCode = 1;
        MessageBox.Show(this, message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        Close();
    }

    private void TrackDownload(object sender, CoreWebView2DownloadStartingEventArgs e)
    {
        var operation = e.DownloadOperation;
        if (operation.State == CoreWebView2DownloadState.InProgress && downloads.Add(operation))
            operation.StateChanged += DownloadStateChanged;
    }

    private void DownloadStateChanged(object sender, object args)
    {
        var operation = (CoreWebView2DownloadOperation)sender;
        if (operation.State == CoreWebView2DownloadState.InProgress) return;
        operation.StateChanged -= DownloadStateChanged;
        downloads.Remove(operation);
    }

    private async Task<bool> CanQuitWithDownloads()
    {
        // WebView2 may have written the last byte while it is still finalizing the file.
        for (int attempt = 0; downloads.Count > 0 && attempt < 20; attempt++)
            await Task.Delay(100);
        if (downloads.Count == 0) return true;
        string language = DesktopSettings.SavedLanguage;
        if (String.IsNullOrEmpty(language) || language == "system")
            language = System.Globalization.CultureInfo.CurrentUICulture.Name;
        string message = language.StartsWith("zh", StringComparison.OrdinalIgnoreCase)
            ? "仍有文件正在下载。要取消未完成的下载并退出吗？"
            : "Files are still downloading. Cancel unfinished downloads and quit?";
        return MessageBox.Show(this, message, Text, MessageBoxButtons.YesNo, MessageBoxIcon.Question,
                               MessageBoxDefaultButton.Button2) == DialogResult.Yes;
    }

    private async void OnClosing(object sender, FormClosingEventArgs e)
    {
        if (closing || !loaded) {
            closing = true;
            if (notifications != null) notifications.Dispose();
            return;
        }
        e.Cancel = true;
        if (checkingClose) return;
        bool quit = quitRequested;
        quitRequested = false;
        if (!quit && e.CloseReason == CloseReason.UserClosing && DesktopSettings.KeepInBackground) {
            tray.Visible = true;
            Hide();
            return;
        }
        checkingClose = true;
        try
        {
            var browser = view.CoreWebView2;
            string result = await browser.ExecuteScriptAsync("window.RunTeamsLocalDesktop?.checkClose(false)");
            bool discard = result == "\"dirty\"";
            if (discard && MessageBox.Show(this, "Discard unsaved changes and quit?", Text,
                MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
            if (!await CanQuitWithDownloads()) return;
            result = await browser.ExecuteScriptAsync("window.RunTeamsLocalDesktop?.prepareClose(" + (discard ? "true" : "false") + ")");
            if (result == "\"ready\"") { closing = true; Close(); }
            else MessageBox.Show(this, "Finish pending changes in the workspace before closing.", Text);
        }
        catch (Exception error) { MessageBox.Show(this, error.Message, Text); }
        finally { checkingClose = false; }
    }
}
