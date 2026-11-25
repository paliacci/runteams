using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Windows.Data.Xml.Dom;
using Windows.UI.Notifications;

internal sealed class DesktopNotifications : IDisposable
{
    internal const string AppId = "RunTeams.Local";
    private readonly Control window;
    private readonly Action restore;
    private readonly Action<bool> delivery;
    private readonly Dictionary<CoreWebView2Notification, ToastNotification> active =
        new Dictionary<CoreWebView2Notification, ToastNotification>();
    private readonly string group = Guid.NewGuid().ToString("N").Substring(0, 16);
    private ToastNotifier notifier;

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

    internal void Show(CoreWebView2Notification note)
    {
        try {
            if (notifier == null) notifier = ToastNotificationManager.CreateToastNotifier(AppId);
            if (notifier.Setting != NotificationSetting.Enabled) {
                note.ReportClosed(); delivery(false); return;
            }
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
            var toast = new ToastNotification(xml) { Group = group, ExpirationTime = DateTimeOffset.Now.AddHours(1) };
            const string prefix = "runteams-work-";
            if (note.Tag.StartsWith(prefix, StringComparison.Ordinal)) toast.Tag = note.Tag.Substring(prefix.Length);
            toast.Activated += (sender, args) => Dispatch(delegate {
                if (!active.ContainsKey(note)) return;
                restore();
                note.ReportClicked();
                Finish(note, false);
            });
            toast.Dismissed += (sender, args) => Dispatch(delegate { Finish(note, false); });
            toast.Failed += (sender, args) => Dispatch(delegate {
                if (active.ContainsKey(note)) { Finish(note, false); delivery(false); }
            });
            active.Add(note, toast);
            note.CloseRequested += CloseRequested;
            notifier.Show(toast);
            note.ReportShown();
            delivery(true);
        } catch (Exception) {
            if (active.ContainsKey(note)) Finish(note, true);
            else note.ReportClosed();
            delivery(false);
        }
    }

    private void CloseRequested(object sender, object args) { Finish((CoreWebView2Notification)sender, true); }

    private void Finish(CoreWebView2Notification note, bool hide)
    {
        ToastNotification toast;
        if (!active.TryGetValue(note, out toast)) return;
        active.Remove(note);
        note.CloseRequested -= CloseRequested;
        try { if (hide) notifier.Hide(toast); }
        finally { note.ReportClosed(); }
    }

    public void Dispose()
    {
        foreach (var note in new List<CoreWebView2Notification>(active.Keys)) Finish(note, true);
    }
}
