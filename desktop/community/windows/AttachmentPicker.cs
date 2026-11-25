using System;
using System.Collections.Generic;
using System.Collections.Specialized;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

internal static class AttachmentPicker
{
    private static string Label(string en, string zh)
    {
        return CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "zh" ? zh : en;
    }

    internal static int Run(string[] args)
    {
        try {
            Application.EnableVisualStyles();
            var flags = new HashSet<string>(args);
            string[] paths;
            if (flags.Contains("--clipboard")) {
                StringCollection files = Clipboard.GetFileDropList();
                paths = new string[files.Count];
                files.CopyTo(paths, 0);
            } else if (flags.Contains("--drop")) {
                // OLE drag data belongs to the target WebView, never the clipboard.
                throw new InvalidOperationException(Label("Choose the local reference from the + menu.", "请从＋菜单选择要引用的文件或文件夹。"));
            } else if (flags.Contains("--folders-only")) {
                paths = Folder(null, flags.Contains("--work-folder"));
            } else if (flags.Contains("--files-only")) {
                paths = Files(null, !flags.Contains("--single"));
            } else {
                paths = Mixed();
            }
            var response = new { cancelled = paths == null, paths = paths ?? new string[0] };
            byte[] json = Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(response));
            using (Stream output = Console.OpenStandardOutput()) output.Write(json, 0, json.Length);
            return 0;
        }
        catch (Exception error) {
            byte[] message = Encoding.UTF8.GetBytes(error.Message);
            using (Stream output = Console.OpenStandardError()) output.Write(message, 0, message.Length);
            return 1;
        }
    }

    private static string[] Files(IWin32Window owner, bool multiple)
    {
        using (var dialog = new OpenFileDialog()) {
            dialog.Title = Label("Choose files", "选择文件");
            dialog.Multiselect = multiple;
            dialog.RestoreDirectory = true;
            return dialog.ShowDialog(owner) == DialogResult.OK ? dialog.FileNames : null;
        }
    }

    private static string[] Folder(IWin32Window owner, bool work)
    {
        var dialog = (IFileDialog)new FileOpenDialog();
        try {
            uint options;
            dialog.GetOptions(out options);
            const uint pickFolders = 0x20, forceFileSystem = 0x40, dontAddToRecent = 0x02000000;
            dialog.SetOptions(options | pickFolders | forceFileSystem | dontAddToRecent);
            dialog.SetTitle(work ? Label("Choose a work folder", "选择工作文件夹") : Label("Choose a folder", "选择文件夹"));
            int status = dialog.Show(owner == null ? IntPtr.Zero : owner.Handle);
            if (status == unchecked((int)0x800704C7)) return null; // ERROR_CANCELLED
            Marshal.ThrowExceptionForHR(status);
            IShellItem item;
            dialog.GetResult(out item);
            try {
                string path;
                item.GetDisplayName(0x80058000, out path); // SIGDN_FILESYSPATH
                return new[] { path };
            } finally { Marshal.ReleaseComObject(item); }
        } finally { Marshal.ReleaseComObject(dialog); }
    }

    [ComImport, Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")]
    private class FileOpenDialog {}

    // The .NET Framework folder browser omits the shell address bar. Use
    // IFileDialog's native folder mode so users can enter drive and UNC paths.
    [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileDialog
    {
        [PreserveSig] int Show(IntPtr owner);
        void SetFileTypes(uint count, IntPtr filters);
        void SetFileTypeIndex(uint index);
        void GetFileTypeIndex(out uint index);
        void Advise(IntPtr events, out uint cookie);
        void Unadvise(uint cookie);
        void SetOptions(uint options);
        void GetOptions(out uint options);
        void SetDefaultFolder(IShellItem folder);
        void SetFolder(IShellItem folder);
        void GetFolder(out IShellItem folder);
        void GetCurrentSelection(out IShellItem item);
        void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
        void GetFileName([MarshalAs(UnmanagedType.LPWStr)] out string name);
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
        void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string label);
        void GetResult(out IShellItem item);
    }

    [ComImport, Guid("43826d1e-e718-42ee-bc55-a1e261c37bfe"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItem
    {
        void BindToHandler(IntPtr context, ref Guid handler, ref Guid iid, out IntPtr result);
        void GetParent(out IShellItem parent);
        void GetDisplayName(uint type, [MarshalAs(UnmanagedType.LPWStr)] out string name);
    }

    private static string[] Mixed()
    {
        using (var form = new Form()) {
            form.Text = Label("Choose files and folders", "选择文件和文件夹");
            form.StartPosition = FormStartPosition.CenterScreen;
            form.ClientSize = new Size(540, 280);
            form.MinimumSize = new Size(440, 220);
            var items = new ListBox { Dock = DockStyle.Fill, HorizontalScrollbar = true };
            var choices = new FlowLayoutPanel { Dock = DockStyle.Top, AutoSize = true };
            var files = new Button { Text = Label("Add files…", "添加文件…"), AutoSize = true };
            var folder = new Button { Text = Label("Add folder…", "添加文件夹…"), AutoSize = true };
            var remove = new Button { Text = Label("Remove", "移除"), AutoSize = true, Enabled = false };
            choices.Controls.AddRange(new Control[] { files, folder, remove });
            var actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, AutoSize = true, FlowDirection = FlowDirection.RightToLeft };
            var cancel = new Button { Text = Label("Cancel", "取消"), DialogResult = DialogResult.Cancel };
            var add = new Button { Text = Label("Add", "添加"), DialogResult = DialogResult.OK, Enabled = false };
            actions.Controls.AddRange(new Control[] { cancel, add });
            form.Controls.AddRange(new Control[] { items, choices, actions });
            form.AcceptButton = add;
            form.CancelButton = cancel;
            Action<string[]> append = delegate(string[] selected) {
                if (selected == null) return;
                foreach (string path in selected)
                    if (!items.Items.Contains(path)) items.Items.Add(path);
                add.Enabled = items.Items.Count > 0;
            };
            files.Click += delegate { append(Files(form, true)); };
            folder.Click += delegate { append(Folder(form, false)); };
            items.SelectedIndexChanged += delegate { remove.Enabled = items.SelectedIndex >= 0; };
            remove.Click += delegate {
                if (items.SelectedIndex >= 0) items.Items.RemoveAt(items.SelectedIndex);
                add.Enabled = items.Items.Count > 0;
            };
            if (form.ShowDialog() != DialogResult.OK) return null;
            var result = new string[items.Items.Count];
            items.Items.CopyTo(result, 0);
            return result;
        }
    }
}
