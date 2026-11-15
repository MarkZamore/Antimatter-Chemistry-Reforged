package lanminecraft.qa;

import java.lang.instrument.Instrumentation;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.FutureTask;
import java.util.concurrent.TimeUnit;
import java.util.function.Function;

/** Checks both locales in the same Forge 1.20.1 client using a disposable world. */
public final class ReforgedQuestLocaleQa {
    private static final Class<?>[] NONE = {};
    private static final Class<?>[] ID = {long.class};
    private static final String MC = "net.minecraft.client.Minecraft";
    private static final String QUESTS = "dev.ftb.mods.ftbquests.";
    private static final String WORLD = "ReforgedQuestsLocaleQa";
    private final Path evidence;
    private final Object client;
    private final ClassLoader loader;

    private ReforgedQuestLocaleQa(Path evidence, Object client) {
        this.evidence = evidence;
        this.client = client;
        this.loader = client.getClass().getClassLoader();
    }

    public static void premain(String args, Instrumentation instrumentation) {
        var worker = new Thread(() -> run(instrumentation), "Reforged quest locale QA");
        worker.setDaemon(true);
        worker.start();
    }

    private static void run(Instrumentation instrumentation) {
        Path root = Path.of(System.getProperty("lanminecraft.steamqa.run"));
        Path game = Path.of(System.getProperty("lanminecraft.steamqa.game"));
        Path evidence = Path.of(System.getProperty("lanminecraft.steamqa.evidence"));
        try {
            if (!Files.isRegularFile(root.resolve("RUN.json"))
                    || !game.toRealPath().startsWith(root.toRealPath())
                    || !evidence.toRealPath().startsWith(root.toRealPath())
                    || Files.exists(game.resolve("saves").resolve(WORLD))) {
                throw new IllegalStateException("Expected a fresh marked fixture");
            }
            // Reflecting on game classes before Forge has set up its event bus can
            // load untransformed classes. Wait until native resource initialization.
            Path log = game.resolve("logs/latest.log");
            waitFor("Forge resource loading", () -> Files.isRegularFile(log)
                    && Files.readString(log).contains("shulker_boxes.png-atlas"));
            Class<?> minecraft = null;
            for (Class<?> loaded : instrumentation.getAllLoadedClasses()) {
                if (loaded.getName().equals(MC)) {
                    minecraft = loaded;
                    break;
                }
            }
            if (minecraft == null) throw new IllegalStateException("Minecraft client was not initialized");
            Object client = minecraft.getMethod("m_91087_").invoke(null);
            var qa = new ReforgedQuestLocaleQa(evidence, client);
            qa.check();
        } catch (Throwable failure) {
            try { Files.writeString(evidence.resolve("failure.txt"), failure.toString()); }
            catch (Exception ignored) {}
            failure.printStackTrace();
            System.exit(1);
        }
    }

    private void check() throws Exception {
        waitFor("main menu", () -> onClient(() -> {
            var screen = client.getClass().getDeclaredField("f_91080_");
            screen.setAccessible(true);
            return type("net.minecraft.client.gui.screens.TitleScreen").isInstance(screen.get(client))
                    && invoke(client, "m_91265_") == null;
        }));
        onClient(() -> { createWorld(); return null; });
        Class<?> questFile = type(QUESTS + "client.ClientQuestFile");
        waitFor("FTB Quests sync", () -> onClient(() -> Boolean.TRUE.equals(questFile.getMethod("exists").invoke(null))));
        onClient(() -> { inspect(questFile.getField("INSTANCE").get(null), "en_us"); return null; });

        CompletableFuture<?> reload = onClient(() -> {
            Object languages = invoke(client, "m_91102_");
            languages.getClass().getMethod("m_264110_", String.class).invoke(languages, "ru_ru");
            return (CompletableFuture<?>) invoke(client, "m_91391_");
        });
        reload.get(360, TimeUnit.SECONDS);
        onClient(() -> {
            inspect(questFile.getField("INSTANCE").get(null), "ru_ru");
            invoke(client, "m_91395_");
            return null;
        });
    }

    private void inspect(Object file, String locale) throws Exception {
        boolean russian = locale.equals("ru_ru");
        String active = (String) invoke(invoke(client, "m_91102_"), "m_264236_");
        expect(locale, active);
        Object intro = file.getClass().getMethod("getChapter", ID).invoke(file, 0x2000000000000000L);
        Object quest = file.getClass().getMethod("getQuest", ID).invoke(file, 0x3000000000000001L);
        Object group = file.getClass().getMethod("getChapterGroup", ID).invoke(file, 0x1000000000000001L);
        Object task = ((List<?>) invoke(quest, "getTasksAsList")).get(0);
        List<?> lines = (List<?>) invoke(quest, "getDescription");
        Object support = file.getClass().getMethod("getQuest", ID).invoke(file, 0x3000000000000006L);
        Object link = ((List<?>) invoke(support, "getDescription")).get(6);
        expect(russian ? "Добро пожаловать" : "Welcome", text(invoke(intro, "getTitle")));
        expect(russian ? "Добро пожаловать" : "Welcome", text(invoke(quest, "getTitle")));
        expect(russian ? "Развитие" : "Progression", text(invoke(group, "getTitle")));
        expect(russian ? "Прочитать" : "Read", text(invoke(quest, "getSubtitle")));
        expect(russian ? "Прочитать" : "Read", text(invoke(task, "getTitle")));
        expect(russian ? "Спасибо, что играете в Antimatter Chemistry Reforged."
                : "Thanks for playing Antimatter Chemistry Reforged.", text(lines.get(0)));
        String address = "piglinmine.com/support/tickets/create";
        expect((russian ? "Создать обращение: " : "Ticket: ") + address, text(link));
        Class<?> component = type("net.minecraft.network.chat.Component");
        Object style = component.getMethod("m_7383_").invoke(link);
        Object click = invoke(style, "m_131182_");
        expect("https://" + address, (String) invoke(click, "m_130623_"));
        Object elements = file.getClass().getMethod("getQuest", ID).invoke(file, 0x3100000000000006L);
        List<?> elementLines = (List<?>) invoke(elements, "getDescription");
        boolean hasPercentages = false;
        for (Object line : elementLines) {
            if (text(line).equals("Fe 18% · C 14% · Si 12% · O 10% · H 8% · Ca 7%")) {
                hasPercentages = true;
                break;
            }
        }
        if (!hasPercentages) throw new IllegalStateException("FTB percentage text did not render intact");

        Object screen = type(QUESTS + "client.ClientQuestFile")
                .getMethod("openGui", type(QUESTS + "quest.Quest"), boolean.class).invoke(null, quest, true);
        if (screen == null) throw new IllegalStateException("The actual FTB quest screen did not open");
        Files.writeString(evidence.resolve(locale + ".txt"),
                String.join("\n", active, text(invoke(intro, "getTitle")), text(invoke(quest, "getTitle")),
                        text(invoke(group, "getTitle")), text(invoke(task, "getTitle")), text(lines.get(0))) + "\n");
    }

    private void createWorld() throws Exception {
        Class<?> settings = type("net.minecraft.world.level.LevelSettings");
        Class<?> mode = type("net.minecraft.world.level.GameType");
        Class<?> difficulty = type("net.minecraft.world.Difficulty");
        Class<?> rules = type("net.minecraft.world.level.GameRules");
        Class<?> data = type("net.minecraft.world.level.WorldDataConfiguration");
        Class<?> options = type("net.minecraft.world.level.levelgen.WorldOptions");
        Class<?> registry = type("net.minecraft.core.RegistryAccess");
        Object levelSettings = settings.getDeclaredConstructor(String.class, mode, boolean.class,
                difficulty, boolean.class, rules, data).newInstance(WORLD, mode.getField("CREATIVE").get(null),
                false, difficulty.getField("NORMAL").get(null), false, rules.getConstructor().newInstance(),
                data.getField("f_244649_").get(null));
        Object worldOptions = options.getMethod("m_247394_").invoke(null);
        var normal = type("net.minecraft.world.level.levelgen.presets.WorldPresets")
                .getDeclaredMethod("m_246552_", registry);
        Function<Object, Object> dimensions = access -> {
            try { return normal.invoke(null, access); }
            catch (ReflectiveOperationException failure) { throw new IllegalStateException(failure); }
        };
        Object flows = invoke(client, "m_231466_");
        flows.getClass().getMethod("m_233157_", String.class, settings, options, Function.class)
                .invoke(flows, WORLD, levelSettings, worldOptions, dimensions);
    }

    private static void waitFor(String phase, Callable<Boolean> check) throws Exception {
        long limit = System.nanoTime() + TimeUnit.MINUTES.toNanos(8);
        while (!check.call()) {
            if (System.nanoTime() > limit) throw new IllegalStateException("Timed out waiting for " + phase);
            Thread.sleep(500);
        }
    }

    private <T> T onClient(Callable<T> work) throws Exception {
        var request = new FutureTask<>(work);
        ((Executor) client).execute(request);
        return request.get(180, TimeUnit.SECONDS);
    }

    private Class<?> type(String name) throws ClassNotFoundException {
        return Class.forName(name, false, loader);
    }

    private static Object invoke(Object target, String method) throws ReflectiveOperationException {
        return target.getClass().getMethod(method, NONE).invoke(target);
    }

    private String text(Object component) throws ReflectiveOperationException {
        return (String) type("net.minecraft.network.chat.Component").getMethod("getString").invoke(component);
    }

    private static void expect(String expected, String actual) {
        if (!expected.equals(actual)) throw new IllegalStateException("Expected " + expected + ", got " + actual);
    }
}
