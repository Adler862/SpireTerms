using Godot;
using MegaCrit.Sts2.Core.Localization;
using MegaCrit.Sts2.Core.Logging;
using MegaCrit.Sts2.Core.Modding;

namespace SpireTermsProbe;

/// <summary>
/// Verification-only mod. Locale tables are loaded *after* mod initialization
/// (see godot.log ordering), so lookups are retried from the SceneTree frame loop
/// until the LocManager actually answers.
/// </summary>
[ModInitializer(nameof(Initialize))]
public static class Probe
{
    private static int _frames;
    private static bool _done;

    public static void Initialize()
    {
        Log.Info("[SPIRETERMS] probe init");
        try
        {
            var tree = Engine.GetMainLoop() as SceneTree;
            if (tree is null)
            {
                Log.Error("[SPIRETERMS] no SceneTree at init");
                return;
            }
            tree.ProcessFrame += OnFrame;
            Log.Info("[SPIRETERMS] subscribed to ProcessFrame");
        }
        catch (System.Exception ex)
        {
            Log.Error($"[SPIRETERMS] init failed: {ex}");
        }
    }

    private static void OnFrame()
    {
        if (_done)
        {
            return;
        }
        _frames++;
        if (_frames == 90 && !_done)
        {
            // Fallback: report whatever the table says, even if it looks untouched,
            // so a failed run still tells us something.
            Log.Info("[SPIRETERMS] --- fallback dump at frame 90 ---");
            Dump("cards", "STRIKE_IRONCLAD.title");
            Dump("cards", "ABRASIVE.description");
            return;
        }
        if (_frames % 30 != 0)
        {
            return;
        }
        try
        {
            var probe = new LocString("cards", "STRIKE_IRONCLAD.title").GetRawText();
            if (string.IsNullOrEmpty(probe) || probe == "cards.STRIKE_IRONCLAD.title")
            {
                return; // table not loaded yet, try again later
            }
        }
        catch (System.Exception)
        {
            return; // LocManager not ready yet
        }

        _done = true;
        Log.Info($"[SPIRETERMS] --- dump begin (frame {_frames}) ---");
        Dump("cards", "STRIKE_IRONCLAD.title");
        Dump("cards", "STRIKE_IRONCLAD.description");
        Dump("cards", "ABRASIVE.description");
        Dump("cards", "ACCURACY.description");
        Dump("cards", "MAD_SCIENCE.title");
        Dump("cards", "THIS_KEY_DOES_NOT_EXIST.title");
        Log.Info("[SPIRETERMS] --- dump end ---");
    }

    private static void Dump(string table, string key)
    {
        try
        {
            var loc = new LocString(table, key);
            Log.Info($"[SPIRETERMS] {table}/{key} RAW={loc.GetRawText()} FMT={loc.GetFormattedText()}");
        }
        catch (System.Exception ex)
        {
            Log.Error($"[SPIRETERMS] {table}/{key} threw {ex.GetType().Name}: {ex.Message}");
        }
    }
}
