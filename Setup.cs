using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

internal static class Setup
{
    const string Key = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\FabWatch";
    const string Release = "1.3.1";
    static readonly string Root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "FabWatch");
    static readonly string App = Path.Combine(Root, "app");
    static readonly string Exe = Path.Combine(App, "FabWatch.exe");
    static readonly string SetupCopy = Path.Combine(Root, "FabWatchSetup.exe");
    static readonly string Shortcut = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs), "Fab Watch.lnk");
    static readonly string DesktopShortcut = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "Fab Watch.lnk");
    static readonly string Icon = Path.Combine(App, "_internal", "fab-watch.ico");
    const string StartupKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    [DllImport("shell32.dll")] static extern void SHChangeNotify(uint evt, uint flags, IntPtr one, IntPtr two);
    static readonly string[] Tasks = { "FabWatch-Check", "FabWatch-Reviews", "FabWatch-TestReviews", "FabWatch-Engine", "FabWatch-EngineReminders" };

    [STAThread]
    static int Main(string[] args)
    {
        bool silent = Array.IndexOf(args, "/silent") >= 0;
        bool remove = Array.IndexOf(args, "/uninstall") >= 0;
        bool fresh = Array.IndexOf(args, "/fresh") >= 0;
        try
        {
            using (var guard = new Mutex(false, @"Local\FabWatchSetup"))
            {
                if (!guard.WaitOne(0)) throw new InvalidOperationException("Another Fab Watch setup is running.");
                try
                {
                    if (!remove && !silent && File.Exists(Path.Combine(Root, "settings.json")))
                    {
                        var choice = MessageBox.Show("A saved Fab Watch profile exists on this computer.\n\nYes: update and keep the profile, history and read confirmations.\nNo: start fresh with an empty Seller URL and no connected seller. The old profile will be backed up.\nCancel: leave everything unchanged.",
                            "Fab Watch Setup", MessageBoxButtons.YesNoCancel, MessageBoxIcon.Question);
                        if (choice == DialogResult.Cancel) return 0;
                        fresh = choice == DialogResult.No;
                    }
                    string question = remove ? "Uninstall Fab Watch? Your activity and settings will be kept. Setup will offer a fresh start if you reinstall."
                        : fresh ? "Install Fab Watch " + Release + " and start fresh? The current profile will be backed up locally."
                        : File.Exists(Exe) ? "Install Fab Watch " + Release + " over the existing version? Your activity and settings will be kept."
                        : "Install Fab Watch " + Release + " for your Windows account?";
                    if (!silent && MessageBox.Show(question, "Fab Watch Setup",
                        MessageBoxButtons.OKCancel, MessageBoxIcon.Question) != DialogResult.OK) return 0;
                    if (remove) Uninstall();
                    else
                    {
                        Install(fresh);
                        if (!silent) Process.Start(Exe);
                    }
                    return 0;
                }
                finally { guard.ReleaseMutex(); }
            }
        }
        catch (Exception e)
        {
            Directory.CreateDirectory(Root);
            File.AppendAllText(Path.Combine(Root, "setup.log"), DateTime.Now + " " + e + Environment.NewLine);
            if (!silent) MessageBox.Show(e.Message, "Fab Watch Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    static void Install(bool fresh)
    {
        using (var key = Registry.CurrentUser.OpenSubKey(Key))
        {
            Version installed;
            if (key != null && Version.TryParse((string)key.GetValue("DisplayVersion"), out installed)
                && installed > new Version(Release))
                throw new InvalidOperationException("A newer version of Fab Watch is already installed.");
        }
        Directory.CreateDirectory(Root);
        string staging = Path.Combine(Root, "stage-" + Guid.NewGuid().ToString("N"));
        string previous = Path.Combine(Root, "previous-" + Guid.NewGuid().ToString("N"));
        string backup = null;
        try
        {
            Extract(staging);
            if (!File.Exists(Path.Combine(staging, "FabWatch.exe"))) throw new InvalidDataException("The application is missing from this setup.");
            CheckClosed();
            if (Directory.Exists(App)) Directory.Move(App, previous);
            try
            {
                Directory.Move(staging, App);
                if (fresh) backup = ArchiveProfile();
                using (var aumid = Registry.CurrentUser.CreateSubKey(@"Software\Classes\AppUserModelId\FabWatch.Desktop"))
                {
                    aumid.SetValue("DisplayName", "Fab Watch");
                    aumid.SetValue("IconUri", Path.Combine(App, "_internal", "fab-watch.png"));
                    aumid.SetValue("IconBackgroundColor", "FF222228");
                }
                if (Run(Exe, "--configure") != 0) throw new InvalidOperationException("Could not configure Fab Watch.");
                string current = Application.ExecutablePath;
                if (!String.Equals(current, SetupCopy, StringComparison.OrdinalIgnoreCase)) File.Copy(current, SetupCopy, true);
                CreateShortcut(Shortcut);
                CreateShortcut(DesktopShortcut);
                using (var protocol = Registry.CurrentUser.CreateSubKey(@"Software\Classes\fabwatch"))
                {
                    protocol.SetValue("", "URL:Fab Watch notifications");
                    protocol.SetValue("URL Protocol", "");
                    using (var command = protocol.CreateSubKey(@"shell\open\command"))
                        command.SetValue("", Quote(Exe) + " --notification-action \"%1\"");
                }
                using (var startup = Registry.CurrentUser.CreateSubKey(StartupKey))
                    startup.SetValue("FabWatch", Quote(Exe) + " --tray");
                SHChangeNotify(0x08000000, 0, IntPtr.Zero, IntPtr.Zero);
                using (var key = Registry.CurrentUser.CreateSubKey(Key))
                {
                    key.SetValue("DisplayName", "Fab Watch");
                    key.SetValue("DisplayVersion", Release);
                    key.SetValue("InstallLocation", App);
                    key.SetValue("DisplayIcon", Icon);
                    key.SetValue("UninstallString", Quote(SetupCopy) + " /uninstall");
                    key.SetValue("NoModify", 1);
                    key.SetValue("NoRepair", 1);
                }
            }
            catch
            {
                if (backup != null) RestoreProfile(backup);
                if (Directory.Exists(App)) Directory.Delete(App, true);
                if (Directory.Exists(previous))
                {
                    Directory.Move(previous, App);
                    Run(Exe, "--configure");
                }
                throw;
            }
            if (Directory.Exists(previous)) Directory.Delete(previous, true);
        }
        finally
        {
            if (Directory.Exists(staging)) Directory.Delete(staging, true);
        }
    }

    static void CheckClosed()
    {
        foreach (string task in Tasks) Run(Path.Combine(Environment.SystemDirectory, "schtasks.exe"), "/End /TN " + task);
        for (int attempt = 0; attempt < 24; attempt++)
        {
            bool running = false;
            foreach (var process in Process.GetProcessesByName("FabWatch"))
            using (process)
            {
                try
                {
                    if (String.Equals(process.MainModule.FileName, Exe, StringComparison.OrdinalIgnoreCase)) running = true;
                }
                catch (System.ComponentModel.Win32Exception) { }
                catch (InvalidOperationException) { }
            }
            if (!running) return;
            Thread.Sleep(250);
        }
        throw new InvalidOperationException("Fab Watch is still running. Right-click its tray icon, choose Exit interface, then try setup again.");
    }

    static string ArchiveProfile()
    {
        string backup = Path.Combine(Root, "backups", DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(backup);
        try
        {
            foreach (string name in new [] { "settings.json", "profiles", "test-reviews", "engine" })
            {
                string source = Path.Combine(Root, name), target = Path.Combine(backup, name);
                if (Directory.Exists(source)) Directory.Move(source, target);
                else if (File.Exists(source)) File.Move(source, target);
            }
            return backup;
        }
        catch { RestoreProfile(backup); throw; }
    }

    static void RestoreProfile(string backup)
    {
        foreach (string name in new [] { "settings.json", "profiles", "test-reviews", "engine" })
        {
            string source = Path.Combine(backup, name), target = Path.Combine(Root, name);
            if (Directory.Exists(source)) Directory.Move(source, target);
            else if (File.Exists(source)) File.Move(source, target);
        }
    }

    static void CreateShortcut(string path)
    {
        dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell", true));
        dynamic link = shell.CreateShortcut(path);
        link.TargetPath = Exe;
        link.WorkingDirectory = App;
        link.Description = "Fab Watch";
        link.IconLocation = Icon + ",0";
        link.Save();
    }

    static void Uninstall()
    {
        CheckClosed();
        if (File.Exists(Exe)) Run(Exe, "--unregister");
        if (Directory.Exists(App)) Directory.Delete(App, true);
        if (File.Exists(Shortcut)) File.Delete(Shortcut);
        if (File.Exists(DesktopShortcut)) File.Delete(DesktopShortcut);
        using (var startup = Registry.CurrentUser.OpenSubKey(StartupKey, true))
            if (startup != null) startup.DeleteValue("FabWatch", false);
        Registry.CurrentUser.DeleteSubKeyTree(Key, false);
        Registry.CurrentUser.DeleteSubKeyTree(@"Software\Classes\AppUserModelId\FabWatch.Desktop", false);
        Registry.CurrentUser.DeleteSubKeyTree(@"Software\Classes\fabwatch", false);
    }

    static void Extract(string destination)
    {
        byte[] payload;
        byte[] expected;
        using (var file = File.OpenRead(Application.ExecutablePath))
        using (var reader = new BinaryReader(file))
        {
            if (file.Length < 48) throw new InvalidDataException("Incomplete setup file.");
            file.Seek(-48, SeekOrigin.End);
            long size = reader.ReadInt64();
            expected = reader.ReadBytes(32);
            if (Encoding.ASCII.GetString(reader.ReadBytes(8)) != "FABWZIP1" || size <= 0 || size > 128 * 1024 * 1024 || size > file.Length - 48)
                throw new InvalidDataException("Invalid setup package.");
            file.Seek(-48 - size, SeekOrigin.End);
            payload = reader.ReadBytes((int)size);
        }
        using (var sha = SHA256.Create())
            if (Convert.ToBase64String(sha.ComputeHash(payload)) != Convert.ToBase64String(expected))
                throw new InvalidDataException("Setup integrity check failed.");
        Directory.CreateDirectory(destination);
        string safeRoot = Path.GetFullPath(destination) + Path.DirectorySeparatorChar;
        using (var archive = new ZipArchive(new MemoryStream(payload), ZipArchiveMode.Read))
            foreach (var entry in archive.Entries)
            {
                string target = Path.GetFullPath(Path.Combine(destination, entry.FullName));
                if (!target.StartsWith(safeRoot, StringComparison.OrdinalIgnoreCase))
                    throw new InvalidDataException("Invalid file path in setup.");
                if (entry.Name.Length == 0) Directory.CreateDirectory(target);
                else
                {
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    entry.ExtractToFile(target);
                }
            }
    }

    static string Quote(string value) { return "\"" + value + "\""; }

    static int Run(string path, string args)
    {
        using (var process = Process.Start(new ProcessStartInfo(path, args) { UseShellExecute = false, CreateNoWindow = true }))
        {
            if (!process.WaitForExit(30000))
            {
                process.Kill();
                throw new TimeoutException("Setup helper timed out.");
            }
            return process.ExitCode;
        }
    }
}
