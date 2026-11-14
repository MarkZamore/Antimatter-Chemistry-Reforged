package lanminecraft.qa;

import java.lang.instrument.Instrumentation;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Arrays;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.Executor;
import java.util.concurrent.TimeUnit;

/** Closes the pinned Supplementaries first-run message using its normal action before standard host QA. */
public final class ReforgedHostQa {
    private static final String MINECRAFT = "net.minecraft.client.Minecraft";
    private static final String WELCOME = "net.mehvahdjukaar.supplementaries.client.screens.WelcomeMessageScreen";

    public static void premain(String args, Instrumentation instrumentation) {
        Forge118SteamQaAgent.premain(args, instrumentation);
        Thread thread = new Thread(() -> dismissWelcome(instrumentation), "Reforged QA onboarding");
        thread.setDaemon(true);
        thread.start();
    }

    private static void dismissWelcome(Instrumentation instrumentation) {
        try {
            Path root = Path.of(System.getProperty("lanminecraft.steamqa.run")).toRealPath();
            Path game = Path.of(System.getProperty("lanminecraft.steamqa.game")).toRealPath();
            Path evidence = Path.of(System.getProperty("lanminecraft.steamqa.evidence")).toRealPath();
            if (!Files.isRegularFile(root.resolve("RUN.json")) ||
                    !game.startsWith(root.resolve("runtime-qa/Minecraft/Personal/Instances")) ||
                    !evidence.startsWith(root.resolve("runtime-qa/evidence"))) return;

            long deadline = System.nanoTime() + Duration.ofMinutes(4).toNanos();
            while (System.nanoTime() < deadline) {
                boolean rendering = Thread.getAllStackTraces().values().stream().flatMap(Arrays::stream)
                        .anyMatch(frame -> frame.getClassName().equals(MINECRAFT) && frame.getMethodName().equals("m_91374_"));
                if (!rendering) {
                    Thread.sleep(300);
                    continue;
                }
                for (Class<?> type : instrumentation.getAllLoadedClasses()) {
                    if (!type.getName().equals(MINECRAFT)) continue;
                    Object client = type.getMethod("m_91087_").invoke(null);
                    if (client == null) continue;
                    var result = new CompletableFuture<Boolean>();
                    ((Executor) client).execute(() -> {
                        try {
                            Object screen = type.getField("f_91080_").get(client);
                            if (screen != null && screen.getClass().getName().equals(WELCOME) &&
                                    Boolean.TRUE.equals(screen.getClass().getMethod("m_6913_").invoke(screen))) {
                                screen.getClass().getMethod("m_7379_").invoke(screen);
                                Files.writeString(evidence.resolve("supplementaries-onboarding.txt"),
                                        "Native ordinary close after the author countdown. Persistent disable was not selected.\n");
                                result.complete(true);
                            } else {
                                result.complete(false);
                            }
                        } catch (Exception failure) {
                            result.completeExceptionally(failure);
                        }
                    });
                    if (result.get(30, TimeUnit.SECONDS)) return;
                }
                Thread.sleep(250);
            }
        } catch (Exception failure) {
            failure.printStackTrace(System.err);
        }
    }
}
