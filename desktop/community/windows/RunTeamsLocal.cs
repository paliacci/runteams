using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
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
    private bool started, closing, checkingClose, loaded;
    private Uri origin;

    [STAThread]
    private static int Main(string[] args)
    {
        Application.EnableVisualStyles();
        try
        {
            using (var window = new LocalWindow(args)) Application.Run(window);
            return Environment.ExitCode;
        }
        catch (Exception error)
        {
            MessageBox.Show(error.Message, "RunTeams Local", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
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
        string core = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "core");
        service.StartInfo = new ProcessStartInfo {
            FileName = Path.Combine(core, @"runtime-dependencies\agent-python\python.exe"),
            Arguments = "-I -B -X utf8 -u -m runteams_core.application.community --owner-stdin --port " + port,
            WorkingDirectory = core, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
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
            browser.Settings.AreHostObjectsAllowed = false;
            browser.Settings.IsWebMessageEnabled = false;
            browser.NavigationStarting += delegate(object sender, CoreWebView2NavigationStartingEventArgs e) {
                Uri destination;
                e.Cancel = !Uri.TryCreate(e.Uri, UriKind.Absolute, out destination)
                    || destination.GetLeftPart(UriPartial.Authority) != origin.GetLeftPart(UriPartial.Authority);
            };
            browser.NewWindowRequested += delegate(object sender, CoreWebView2NewWindowRequestedEventArgs e) {
                e.Handled = true;
                Uri url;
                if (e.IsUserInitiated && Uri.TryCreate(e.Uri, UriKind.Absolute, out url)
                    && (url.Scheme == "https" || url.Scheme == "http"))
                    Process.Start(new ProcessStartInfo(url.AbsoluteUri) { UseShellExecute = true });
            };
            browser.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                if (e.IsSuccess) loaded = true;
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

    private void Fail(string message)
    {
        closing = true;
        Environment.ExitCode = 1;
        MessageBox.Show(this, message, Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
        Close();
    }

    private async void OnClosing(object sender, FormClosingEventArgs e)
    {
        if (closing || !loaded) { closing = true; return; }
        e.Cancel = true;
        if (checkingClose) return;
        checkingClose = true;
        try
        {
            var browser = view.CoreWebView2;
            string result = await browser.ExecuteScriptAsync("window.RunTeamsLocalDesktop?.checkClose(false)");
            bool discard = result == "\"dirty\"";
            if (discard && MessageBox.Show(this, "Discard unsaved changes and quit?", Text,
                MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
            result = await browser.ExecuteScriptAsync("window.RunTeamsLocalDesktop?.prepareClose(" + (discard ? "true" : "false") + ")");
            if (result == "\"ready\"") { closing = true; Close(); }
            else MessageBox.Show(this, "Finish pending changes in the workspace before closing.", Text);
        }
        catch (Exception error) { MessageBox.Show(this, error.Message, Text); }
        finally { checkingClose = false; }
    }
}
