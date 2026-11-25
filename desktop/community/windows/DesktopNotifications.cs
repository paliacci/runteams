using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;
using Microsoft.Win32;
using Microsoft.Web.WebView2.Core;
using Windows.Data.Xml.Dom;
using Windows.UI.Notifications;

internal sealed class DesktopNotifications : IDisposable
{
    internal const string AppId = "RunTeams.Local";
    private readonly Control window;
    private readonly Action restore;
    private readonly Action<bool> delivery;
    private const string Scheme = "runteams-local-notification";
    private const string UriPrefix = Scheme + "://open/";
    private const string EventPrefix = @"Local\RunTeams.Local.Notification.";
    private sealed class Entry : IDisposable
    {
        internal ToastNotification Toast;
        internal EventWaitHandle Signal;
        internal RegisteredWaitHandle Listener;
        public void Dispose()
        {
            if (Listener != null) Listener.Unregister(null);
            if (Signal != null) Signal.Dispose();
        }
    }
    private readonly Dictionary<CoreWebView2Notification, Entry> active =
        new Dictionary<CoreWebView2Notification, Entry>();
    private readonly string group = Guid.NewGuid().ToString("N").Substring(0, 16);
    private ToastNotifier notifier;

    // Action Center can activate a toast after its banner and its WinRT event subscription have expired.
    internal static int OpenNotification(string[] args)
    {
        Guid id;
        if (args.Length != 2 || !args[1].StartsWith(UriPrefix, StringComparison.OrdinalIgnoreCase) ||
            !Guid.TryParseExact(args[1].Substring(UriPrefix.Length), "N", out id)) return 2;
        try {
            using (var signal = EventWaitHandle.OpenExisting(EventPrefix + id.ToString("N"),
                    System.Security.AccessControl.EventWaitHandleRights.Modify)) signal.Set();
            return 0;
        } catch (WaitHandleCannotBeOpenedException) { return 0; } // The originating window or notification has closed.
        catch (UnauthorizedAccessException) { return 1; }
    }

    private static bool ProtocolRegistered()
    {
        string expected = "\"" + Application.ExecutablePath + "\" --open-notification \"%1\"";
        string command = Registry.GetValue(@"HKEY_CLASSES_ROOT\" + Scheme + @"\shell\open\command", "", null) as string;
        return String.Equals(command, expected, StringComparison.OrdinalIgnoreCase);
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    internal static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    internal DesktopNotifications(Control window, Action restore, Action<bool> delivery)
    {
        this.window = window;
        this.restore = restore;
        this.delivery = delivery;
    }

    private void Dispatch(Action action)
    {
        if (!window.IsHandleCreated || window.IsDisposed) return;
        try { window.BeginInvoke(action); }
        catch (InvalidOperationException) { }
    }

    internal static bool? SystemEnabled()
    {
        try { return ToastNotificationManager.CreateToastNotifier(AppId).Setting == NotificationSetting.Enabled; }
        catch (Exception) { return null; } // A new sender has no record until its first notification.
    }

    internal void Show(CoreWebView2Notification note)
    {
        try {
            if (notifier == null) notifier = ToastNotificationManager.CreateToastNotifier(AppId);
            if (SystemEnabled() == false) {
                delivery(false); note.ReportClosed(); return;
            }
            foreach (var entry in new List<KeyValuePair<CoreWebView2Notification, Entry>>(active))
                if (entry.Value.Toast.ExpirationTime <= DateTimeOffset.Now || entry.Key.Tag == note.Tag)
                    Finish(entry.Key, true);
            var xml = new XmlDocument();
            xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text/><text/></binding></visual></toast>");
            var text = xml.GetElementsByTagName("text");
            text[0].AppendChild(xml.CreateTextNode(note.Title));
            text[1].AppendChild(xml.CreateTextNode(note.Body));
            if (note.IsSilent) {
                var audio = xml.CreateElement("audio");
                audio.SetAttribute("silent", "true");
                xml.DocumentElement.AppendChild(audio);
            }
            var current = new Entry();
            active.Add(note, current);
            if (ProtocolRegistered()) {
                string token = Guid.NewGuid().ToString("N");
                xml.DocumentElement.SetAttribute("activationType", "protocol");
                xml.DocumentElement.SetAttribute("launch", UriPrefix + token);
                current.Signal = new EventWaitHandle(false, EventResetMode.AutoReset, EventPrefix + token);
                current.Listener = ThreadPool.RegisterWaitForSingleObject(current.Signal,
                    delegate { Dispatch(delegate { Click(note); }); }, null, -1, true);
            }
            var toast = current.Toast = new ToastNotification(xml) { Group = group, ExpirationTime = DateTimeOffset.Now.AddHours(1) };
            const string prefix = "runteams-work-";
            if (note.Tag.StartsWith(prefix, StringComparison.Ordinal)) toast.Tag = note.Tag.Substring(prefix.Length);
            toast.Activated += (sender, args) => Dispatch(delegate { Click(note); });
            toast.Dismissed += (sender, args) => {
                // A timed-out banner is still available in Windows Action Center.
                if (args.Reason != ToastDismissalReason.TimedOut) Dispatch(delegate { Finish(note, false); });
            };
            toast.Failed += (sender, args) => Dispatch(delegate {
                if (active.ContainsKey(note)) { Finish(note, false); delivery(false); }
            });
            note.CloseRequested += CloseRequested;
            notifier.Show(toast);
            note.ReportShown();
            delivery(true);
        } catch (Exception) {
            delivery(false);
            if (active.ContainsKey(note)) Finish(note, true);
            else note.ReportClosed();
        }
    }

    private void CloseRequested(object sender, object args) { Finish((CoreWebView2Notification)sender, true); }

    private void Click(CoreWebView2Notification note)
    {
        Entry entry;
        if (!active.TryGetValue(note, out entry)) return;
        try {
            if (entry.Toast.ExpirationTime > DateTimeOffset.Now) { restore(); note.ReportClicked(); }
        } finally { Finish(note, false); }
    }

    private void Finish(CoreWebView2Notification note, bool hide)
    {
        Entry entry;
        if (!active.TryGetValue(note, out entry)) return;
        active.Remove(note);
        entry.Dispose();
        note.CloseRequested -= CloseRequested;
        try { if (hide && entry.Toast != null) notifier.Hide(entry.Toast); }
        catch (COMException) { /* Windows may already have removed the toast. */ }
        try { note.ReportClosed(); }
        catch (InvalidOperationException) { /* The document that received the alert has closed. */ }
    }

    public void Dispose()
    {
        foreach (var note in new List<CoreWebView2Notification>(active.Keys)) Finish(note, true);
        if (notifier != null) {
            try { ToastNotificationManager.History.RemoveGroup(group, AppId); }
            catch (COMException) { /* The notification store can be unavailable during Windows shutdown. */ }
        }
    }
}
