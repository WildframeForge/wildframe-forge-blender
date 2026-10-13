// Copyright Wildframe Forge 2026. All Rights Reserved.
// Wildframe Forge Hub - tray icon.
// Started by the hub (hub.js). Shows which apps are connected and the delivery mailbox, notifies about
// deliveries and apps that closed unexpectedly, and closes itself when the hub stops.
// Built with the .NET Framework compiler that ships with Windows (see Scripts/Package-Fab.ps1):
//   csc /target:winexe /r:System.Web.Extensions.dll WildframeForgeHub.cs
using System;
using System.Collections;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.IO;
using System.Net;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("Wildframe Forge Hub")]
[assembly: System.Reflection.AssemblyCompany("Wildframe Forge")]
[assembly: System.Reflection.AssemblyProduct("Wildframe Forge Bridge")]
[assembly: System.Reflection.AssemblyVersion("1.0.0.0")]

namespace WildframeForge
{
    static class Program
    {
        [STAThread]
        static int Main(string[] args)
        {
            bool created;
            using (var mutex = new Mutex(true, "WildframeForgeHubTray", out created))
            {
                if (!created)
                {
                    // One tray icon per user session. The tray of a hub that just closed notices within ~5 s and
                    // exits: wait for it instead of leaving the new hub without an icon.
                    bool acquired;
                    try { acquired = mutex.WaitOne(8000); }
                    catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired) return 0;
                }
                int pid = 0, port = 47811;
                string edition = "standard";
                for (int i = 0; i + 1 < args.Length; i++)
                {
                    if (args[i] == "--hub-pid") int.TryParse(args[i + 1], out pid);
                    else if (args[i] == "--port") int.TryParse(args[i + 1], out port);
                    else if (args[i] == "--edition") edition = args[i + 1];
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new TrayContext(pid, port, edition));
            }
            return 0;
        }
    }

    class TrayContext : ApplicationContext
    {
        readonly int hubPid, port;
        readonly string edition;
        readonly NotifyIcon icon;
        readonly System.Windows.Forms.Timer timer;
        readonly JavaScriptSerializer json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        int failures;
        int lastWaiting = -1;
        readonly HashSet<string> seenCrashes = new HashSet<string>();
        bool firstPoll = true;
        Dictionary<string, object> last;
        string balloonDocument;

        public TrayContext(int hubPid, int port, string edition)
        {
            this.hubPid = hubPid; this.port = port; this.edition = edition;
            icon = new NotifyIcon { Icon = MakeIcon(), Visible = true, Text = "Wildframe Forge Hub - starting" };
            icon.ContextMenuStrip = new ContextMenuStrip();
            icon.ContextMenuStrip.Opening += (s, e) => BuildMenu();
            icon.BalloonTipClicked += (s, e) => { if (balloonDocument != null) OpenDocument(balloonDocument); };
            icon.MouseClick += (s, e) => { if (e.Button == MouseButtons.Left) ShowSummary(); };
            BuildMenu();
            timer = new System.Windows.Forms.Timer { Interval = 5000 };
            timer.Tick += (s, e) => Poll();
            timer.Start();
            Poll();
        }

        string Title { get { return edition == "complete" ? "Wildframe Forge Bridge Complete" : "Wildframe Forge Bridge"; } }

        // ---------- hub API ----------
        string Request(string method, string route, string body)
        {
            var req = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + route);
            req.Method = method;
            req.Timeout = 4000;
            req.Headers["x-wfab-client"] = "tray";
            req.Proxy = null;
            if (body != null)
            {
                var bytes = Encoding.UTF8.GetBytes(body);
                req.ContentType = "application/json";
                req.ContentLength = bytes.Length;
                using (var s = req.GetRequestStream()) s.Write(bytes, 0, bytes.Length);
            }
            using (var res = (HttpWebResponse)req.GetResponse())
            using (var r = new StreamReader(res.GetResponseStream(), Encoding.UTF8)) return r.ReadToEnd();
        }

        Dictionary<string, object> Get(string route)
        {
            return json.Deserialize<Dictionary<string, object>>(Request("GET", route, null));
        }

        void Post(string route, string body)
        {
            try { Request("POST", route, body ?? "{}"); } catch (Exception e) { Notify("Hub", e.Message, ToolTipIcon.Warning, null); }
        }

        bool HubProcessAlive()
        {
            if (hubPid <= 0) return true;
            try { return !Process.GetProcessById(hubPid).HasExited; } catch { return false; }
        }

        // ---------- polling ----------
        void Poll()
        {
            if (!HubProcessAlive()) { Quit(); return; }
            try
            {
                last = Get("/status");
                failures = 0;
            }
            catch
            {
                if (++failures >= 3) Quit();
                return;
            }
            int apps = List(last, "apps").Count + List(last, "unrealAndBlender").Count;
            var d = Dict(last, "deliveries");
            int waiting = Int(d, "waiting"), failed = Int(d, "failed");
            string tip = "Wildframe Forge Hub - " + apps + " app" + (apps == 1 ? "" : "s");
            if (waiting > 0) tip += ", " + waiting + " waiting";
            if (failed > 0) tip += ", " + failed + " failed";
            icon.Text = tip.Length > 63 ? tip.Substring(0, 63) : tip;

            if (!firstPoll && waiting > lastWaiting && lastWaiting >= 0)
                Notify("Delivery waiting", (waiting - lastWaiting) + " package(s) will be imported when the receiving app opens.", ToolTipIcon.Info, null);
            if (!firstPoll && lastWaiting > 0 && waiting < lastWaiting)
                Notify("Delivered", (lastWaiting - waiting) + " package(s) imported.", ToolTipIcon.Info, null);
            lastWaiting = waiting;

            foreach (var c in List(last, "crashes"))
            {
                var crash = c as Dictionary<string, object>;
                if (crash == null) continue;
                string key = Str(crash, "app") + ":" + Str(crash, "pid");
                if (!seenCrashes.Add(key) || firstPoll) continue;
                string doc = Str(crash, "document");
                string app = Str(crash, "app") == "unreal" ? "Unreal Engine" : "Blender";
                string file = string.IsNullOrEmpty(doc) ? "" : Path.GetFileName(doc) + ". ";
                if (Str(crash, "reopen") == "yes")
                    Notify(app + " crashed - reopening it", file + "Opening it again in a few seconds. Waiting deliveries are kept. (Turn this off in the tray menu.)", ToolTipIcon.Warning, null);
                else
                    Notify(app + " closed unexpectedly", file + (string.IsNullOrEmpty(Str(crash, "reopenSkipped")) ? "" : "Not reopened: " + Str(crash, "reopenSkipped") + ". ") + (string.IsNullOrEmpty(doc) ? "" : "Click to open it again. ") + "Waiting deliveries are kept.", ToolTipIcon.Warning, doc);
            }
            firstPoll = false;
        }

        void Notify(string title, string text, ToolTipIcon kind, string document)
        {
            balloonDocument = string.IsNullOrEmpty(document) ? null : document;
            icon.ShowBalloonTip(6000, title, text, kind);
        }

        // ---------- menu ----------
        void BuildMenu()
        {
            var m = icon.ContextMenuStrip;
            m.Items.Clear();
            var head = new ToolStripMenuItem(Title + (last != null ? "  (hub " + Str(last, "hub") + ")" : "")) { Enabled = false };
            m.Items.Add(head);
            var setupItem = new ToolStripMenuItem("Setup...  (Blender, AI apps" + (edition == "complete" ? ", Adobe" : "") + ")");
            setupItem.Click += (s, e) => OpenPage("/setup/link", "Setup");
            m.Items.Add(setupItem);
            m.Items.Add(new ToolStripSeparator());

            var appsMenu = new ToolStripMenuItem("Connected apps");
            int count = 0;
            if (last != null)
            {
                foreach (var a in List(last, "unrealAndBlender"))
                {
                    var x = a as Dictionary<string, object>;
                    string name = Str(x, "app") == "unreal" ? "Unreal Engine" : "Blender";
                    string doc = Str(x, "document");
                    appsMenu.DropDownItems.Add(new ToolStripMenuItem(name + (string.IsNullOrEmpty(doc) ? "" : " - " + Path.GetFileName(doc))) { Enabled = false });
                    count++;
                }
                foreach (var a in List(last, "apps"))
                {
                    var x = a as Dictionary<string, object>;
                    appsMenu.DropDownItems.Add(new ToolStripMenuItem(AdobeName(Str(x, "app")) + " (" + Str(x, "runtime").ToUpper() + ", " + Str(x, "commands") + " commands)") { Enabled = false });
                    count++;
                }
            }
            if (count == 0) appsMenu.DropDownItems.Add(new ToolStripMenuItem("No apps open") { Enabled = false });
            appsMenu.Text = "Connected apps (" + count + ")";
            m.Items.Add(appsMenu);

            if (edition == "complete")
            {
                var scriptsItem = new ToolStripMenuItem("AI Scripts for Adobe apps (any chat AI)...");
                scriptsItem.Click += (s, e) => OpenPage("/scripts/link", "AI Scripts");
                m.Items.Add(scriptsItem);
            }

            var deliveries = new ToolStripMenuItem("Deliveries");
            try
            {
                var dl = Get("/deliveries?limit=15");
                var sum = Dict(dl, "summary");
                deliveries.Text = "Deliveries (" + Int(sum, "waiting") + " waiting, " + Int(sum, "failed") + " failed)";
                foreach (var p in List(dl, "packages"))
                {
                    var x = p as Dictionary<string, object>;
                    string items = string.Join(", ", ToStrings(List(x, "items"), 3));
                    var it = new ToolStripMenuItem(Str(x, "status") + ": " + Str(x, "source") + " -> " + Str(x, "target") + "  " + items);
                    string folder = Str(x, "package");
                    it.Click += (s, e) => OpenFolder(folder);
                    if (Str(x, "status") == "failed")
                    {
                        var retry = new ToolStripMenuItem("Retry");
                        string id = Str(x, "id");
                        retry.Click += (s, e) => Post("/deliveries/update", "{\"package\":" + json.Serialize(id) + ",\"status\":\"waiting\"}");
                        it.DropDownItems.Add(retry);
                        it.ToolTipText = Str(x, "error");
                    }
                    deliveries.DropDownItems.Add(it);
                }
                if (deliveries.DropDownItems.Count == 0) deliveries.DropDownItems.Add(new ToolStripMenuItem("Nothing waiting") { Enabled = false });
                deliveries.DropDownItems.Add(new ToolStripSeparator());
                var open = new ToolStripMenuItem("Open exchange folder");
                string root = Str(sum, "folder");
                open.Click += (s, e) => OpenFolder(root);
                deliveries.DropDownItems.Add(open);
                var clear = new ToolStripMenuItem("Delete delivered packages");
                clear.Click += (s, e) => Post("/deliveries/cleanup", "{\"which\":\"delivered\"}");
                deliveries.DropDownItems.Add(clear);
                var clearAll = new ToolStripMenuItem("Delete ALL packages (including waiting)...");
                clearAll.Click += (s, e) =>
                {
                    if (MessageBox.Show("Delete every package in the exchange folder, including deliveries that are still waiting for an app?", "Wildframe Forge Hub", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) == DialogResult.Yes)
                        Post("/deliveries/cleanup", "{\"which\":\"all\"}");
                };
                deliveries.DropDownItems.Add(clearAll);
            }
            catch { deliveries.Enabled = false; }
            m.Items.Add(deliveries);

            m.Items.Add(new ToolStripSeparator());
            bool keep = false, autoImport = true, reopen = true;
            try
            {
                var st = Get("/settings");
                keep = st.ContainsKey("keepRunning") && Convert.ToBoolean(st["keepRunning"]);
                autoImport = !st.ContainsKey("autoImport") || Convert.ToBoolean(st["autoImport"]);
                reopen = !st.ContainsKey("reopenAfterCrash") || Convert.ToBoolean(st["reopenAfterCrash"]);
            }
            catch { }
            var keepItem = new ToolStripMenuItem("Keep running when all apps are closed") { Checked = keep };
            keepItem.Click += (s, e) => Post("/settings", "{\"keepRunning\":" + (!keep ? "true" : "false") + "}");
            m.Items.Add(keepItem);
            var autoItem = new ToolStripMenuItem("Import deliveries automatically") { Checked = autoImport };
            autoItem.Click += (s, e) => Post("/settings", "{\"autoImport\":" + (!autoImport ? "true" : "false") + "}");
            m.Items.Add(autoItem);
            var reopenItem = new ToolStripMenuItem("Reopen Unreal and Blender after a crash (not after you close them)") { Checked = reopen };
            reopenItem.Click += (s, e) => Post("/settings", "{\"reopenAfterCrash\":" + (!reopen ? "true" : "false") + "}");
            m.Items.Add(reopenItem);
            // Opt-in only: off by default, the buyer ticks it. For people who only use Photoshop, whose plugin
            // cannot start the hub itself.
            bool atLogin = StartsWithWindows();
            var loginItem = new ToolStripMenuItem("Start with Windows (for Photoshop-only use; keeps the hub running)") { Checked = atLogin };
            loginItem.Click += (s, e) => SetStartWithWindows(!atLogin);
            m.Items.Add(loginItem);
            var logItem = new ToolStripMenuItem("Open hub log");
            logItem.Click += (s, e) => OpenFolder(Path.Combine(StateDir(), "Hub"));
            m.Items.Add(logItem);
            m.Items.Add(new ToolStripSeparator());
            var quit = new ToolStripMenuItem("Close the hub");
            // The user asked to close it: force, even while AI calls run or Adobe panels are connected.
            quit.Click += (s, e) => { Post("/shutdown", "{\"force\":true,\"client\":\"tray menu\"}"); Quit(); };
            m.Items.Add(quit);
        }

        void ShowSummary()
        {
            if (last == null) return;
            int apps = List(last, "apps").Count + List(last, "unrealAndBlender").Count;
            var d = Dict(last, "deliveries");
            var life = Dict(last, "lifecycle");
            string closes = life != null && life.ContainsKey("closesInSec") && life["closesInSec"] != null
                ? " Closes in " + Math.Max(1, Int(life, "closesInSec") / 60) + " min." : "";
            Notify(Title, apps + " app(s) connected. Deliveries: " + Int(d, "waiting") + " waiting, " + Int(d, "failed") + " failed." + closes, ToolTipIcon.None, null);
        }

        // ---------- helpers ----------
        static string StateDir()
        {
            return Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WildframeForge");
        }

        // The hub builds the page link (it carries a key only local programs can get), then the default browser opens it.
        // Used for the AI Scripts page (/scripts/link) and the Setup page (/setup/link).
        void OpenPage(string linkRoute, string name)
        {
            try
            {
                var r = Get(linkRoute);
                string url = Str(r, "url");
                if (url.StartsWith("http://127.0.0.1:")) Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch (Exception e) { Notify(name, "Could not open the page: " + e.Message, ToolTipIcon.Warning, null); }
        }

        // ---------- start with Windows (user opt-in) ----------
        const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
        const string RunName = "WildframeForgeHub";

        static bool StartsWithWindows()
        {
            try { using (var k = Microsoft.Win32.Registry.CurrentUser.OpenSubKey(RunKey)) return k != null && k.GetValue(RunName) != null; }
            catch { return false; }
        }

        void SetStartWithWindows(bool on)
        {
            try
            {
                using (var k = Microsoft.Win32.Registry.CurrentUser.CreateSubKey(RunKey))
                {
                    if (on)
                    {
                        var launch = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(StateDir(), "Hub", "launch.json")));
                        string node = Str(launch, "node"), hub = Str(launch, "hub");
                        if (!File.Exists(node) || !File.Exists(hub)) throw new Exception("the hub's launch file points to a missing program; open Wildframe Forge Setup in Unreal and click Fix all");
                        k.SetValue(RunName, "\"" + node + "\" \"" + hub + "\"");
                    }
                    else k.DeleteValue(RunName, false);
                }
                Post("/settings", "{\"keepRunning\":" + (on ? "true" : "false") + "}");
                Notify("Wildframe Forge Hub", on ? "The hub now starts with Windows and stays running. Untick this in the menu to stop." : "The hub no longer starts with Windows.", ToolTipIcon.Info, null);
            }
            catch (Exception e) { Notify("Start with Windows", "Could not change it: " + e.Message, ToolTipIcon.Warning, null); }
        }

        static void OpenFolder(string folder)
        {
            try { if (!string.IsNullOrEmpty(folder) && Directory.Exists(folder)) Process.Start("explorer.exe", "\"" + folder + "\""); } catch { }
        }

        static void OpenDocument(string doc)
        {
            try { if (File.Exists(doc)) Process.Start(new ProcessStartInfo(doc) { UseShellExecute = true }); } catch { }
        }

        static string AdobeName(string id)
        {
            switch (id)
            {
                case "aftereffects": return "After Effects";
                case "premiere": return "Premiere Pro";
                case "photoshop": return "Photoshop";
                case "illustrator": return "Illustrator";
                case "animate": return "Animate";
                default: return id;
            }
        }

        static ArrayList List(Dictionary<string, object> d, string key)
        {
            object v;
            if (d != null && d.TryGetValue(key, out v) && v is ArrayList) return (ArrayList)v;
            return new ArrayList();
        }

        static Dictionary<string, object> Dict(Dictionary<string, object> d, string key)
        {
            object v;
            if (d != null && d.TryGetValue(key, out v)) return v as Dictionary<string, object>;
            return null;
        }

        static string Str(Dictionary<string, object> d, string key)
        {
            object v;
            return d != null && d.TryGetValue(key, out v) && v != null ? Convert.ToString(v) : "";
        }

        static int Int(Dictionary<string, object> d, string key)
        {
            object v;
            try { return d != null && d.TryGetValue(key, out v) && v != null ? Convert.ToInt32(v) : 0; } catch { return 0; }
        }

        static IEnumerable<string> ToStrings(ArrayList a, int max)
        {
            int n = 0;
            foreach (var x in a) { if (n++ >= max) { yield return "..."; yield break; } yield return Convert.ToString(x); }
        }

        // The Wildframe Forge emblem (embedded emblem.ico, small-icon size); the drawn badge below if it is missing.
        static Icon MakeIcon()
        {
            try
            {
                using (var stream = typeof(TrayContext).Assembly.GetManifestResourceStream("WildframeForgeHub.emblem.ico"))
                    if (stream != null) return new Icon(stream, SystemInformation.SmallIconSize);
            }
            catch { }
            return DrawnIcon();
        }

        // Dark round badge with a red forge flame, drawn at runtime (fallback).
        static Icon DrawnIcon()
        {
            var bmp = new Bitmap(32, 32);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode = SmoothingMode.AntiAlias;
                g.Clear(Color.Transparent);
                using (var bg = new SolidBrush(Color.FromArgb(255, 22, 22, 26))) g.FillEllipse(bg, 1, 1, 30, 30);
                using (var ring = new Pen(Color.FromArgb(255, 200, 30, 40), 2.5f)) g.DrawEllipse(ring, 2, 2, 28, 28);
                using (var flame = new GraphicsPath())
                {
                    flame.AddBezier(16, 6, 23, 13, 23, 18, 21, 22);
                    flame.AddBezier(21, 22, 19, 26, 13, 26, 11, 22);
                    flame.AddBezier(11, 22, 9, 18, 12, 14, 16, 6);
                    using (var fill = new LinearGradientBrush(new Rectangle(8, 6, 16, 21), Color.FromArgb(255, 255, 210, 120), Color.FromArgb(255, 210, 30, 30), 90f))
                        g.FillPath(fill, flame);
                }
                using (var anvil = new SolidBrush(Color.FromArgb(255, 210, 210, 215))) g.FillRectangle(anvil, 9, 24, 14, 3);
            }
            return Icon.FromHandle(bmp.GetHicon());
        }

        void Quit()
        {
            timer.Stop();
            icon.Visible = false;
            icon.Dispose();
            ExitThread();
        }
    }
}
