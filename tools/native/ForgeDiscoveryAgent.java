package lanminecraft.qa;

import java.lang.instrument.Instrumentation;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.HexFormat;
import java.util.List;
import java.util.TreeMap;
import java.util.stream.Collectors;

/** Captures stock client Forge discovery after JarJar and dependency validation, before a window or world can open. */
public final class ForgeDiscoveryAgent {
    private static final String PREFIX = "lanminecraft.discovery.";
    private static final String FML = "net.minecraftforge.fml.loading.FMLLoader";

    public static void premain(String ignored, Instrumentation instrumentation) {
        Thread worker = new Thread(() -> collect(instrumentation), "LANMinecraft Forge discovery QA");
        worker.setDaemon(true);
        worker.start();
    }

    private static void collect(Instrumentation instrumentation) {
        try {
            Path run = Path.of(System.getProperty(PREFIX + "run")).toRealPath();
            Path game = run.resolve("native-discovery-game").toRealPath();
            Path receipt = run.resolve("evidence/forge-discovery.tsv");
            if (!run.getParent().getFileName().toString().equals("agent-runs") ||
                    !Files.isRegularFile(run.resolve("RUN.json")) || !game.startsWith(run) ||
                    !receipt.getParent().toRealPath().startsWith(run) || Files.exists(receipt)) {
                throw new IllegalStateException("Discovery requires a fresh isolated stage");
            }
            long deadline = System.nanoTime() + Duration.ofSeconds(90).toNanos();
            while (System.nanoTime() < deadline) {
                for (Class<?> candidate : instrumentation.getAllLoadedClasses()) {
                    if (!candidate.getName().equals(FML)) continue;
                    Object list = candidate.getMethod("getLoadingModList").invoke(null);
                    if (list == null) continue;
                    Path path = (Path) candidate.getMethod("getGamePath").invoke(null);
                    Object side = candidate.getMethod("getDist").invoke(null);
                    if (!game.equals(path.toRealPath()) || !"CLIENT".equals(side.toString()) ||
                            !((List<?>) call(list, "getErrors")).isEmpty() || !((List<?>) call(list, "getBrokenFiles")).isEmpty()) {
                        throw new IllegalStateException("Forge did not finish clean client-side discovery in the test directory");
                    }
                    writeReceipt(list, receipt);
                    System.exit(0);
                }
                Thread.sleep(40);
            }
            throw new IllegalStateException("Forge discovery timed out");
        } catch (Exception failure) {
            failure.printStackTrace(System.err);
            System.exit(1);
        }
    }

    private static void writeReceipt(Object list, Path receipt) throws Exception {
        TreeMap<String, String> mods = new TreeMap<>();
        for (Object info : (Iterable<?>) call(list, "getMods")) {
            String id = (String) call(info, "getModId");
            String name = (String) call(info, "getDisplayName");
            String version = call(info, "getVersion").toString();
            Path path = (Path) call(call(call(info, "getOwningFile"), "getFile"), "getFilePath");
            String uri = path.toUri().toString().replace('\\', '/');
            int local = uri.lastIndexOf("/mods/");
            String owner = local < 0 ? "" : uri.substring(local + 1);
            String filename = path.getFileName().toString();
            String row = List.of(id, name, version, filename, owner).stream()
                    .map(value -> HexFormat.of().formatHex(value.getBytes(StandardCharsets.UTF_8)))
                    .collect(Collectors.joining("\t"));
            if (mods.put(id, row) != null) throw new IllegalStateException("Duplicate loaded mod " + id);
        }
        if (!mods.keySet().containsAll(List.of("minecraft", "forge", "e4steam", "ftbquests", "kubejs", "alchemistry", "openloader"))) {
            throw new IllegalStateException("Forge discovery did not include the pinned transport and core pack mods");
        }
        Files.write(receipt, mods.values());
        System.out.println("[ForgeDiscoveryQA] " + mods.size() + " loaded client-side mod IDs");
    }

    private static Object call(Object owner, String name) throws ReflectiveOperationException {
        Method method = owner.getClass().getMethod(name);
        method.trySetAccessible();
        return method.invoke(owner);
    }
}
