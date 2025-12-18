import sys
import os
import math
from pathlib import Path
import warnings
import subprocess
import shutil


# ================= 库配置与初始化 =================

class OsuEnvironment:
    """管理 .NET 运行时和 DLL 加载的单例类"""
    _initialized = False

    @classmethod
    def _check_dotnet_installed(cls):
        """检查系统是否安装了 .NET 8 Runtime"""

        # 1. 检查 dotnet 命令是否存在
        dotnet_path = shutil.which("dotnet")
        if not dotnet_path:
            raise RuntimeError(
                "【致命错误】未检测到 'dotnet' 命令。\n"
                "请安装 .NET 8 Runtime：\n"
                "👉 https://dotnet.microsoft.com/en-us/download/dotnet/8.0"
            )

        # 2. 检查具体的 Runtime 版本
        try:
            # 运行 dotnet --list-runtimes 查看已安装版本
            result = subprocess.run(
                ["dotnet", "--list-runtimes"],
                capture_output=True,
                text=True,
                check=True
            )
            output = result.stdout

            # 检查是否有 Microsoft.NETCore.App 8.0.x
            # 匹配逻辑：包含 "Microsoft.NETCore.App 8."
            if "Microsoft.NETCore.App 8." not in output:
                raise RuntimeError(
                    f"【版本错误】检测到 dotnet，但未找到 .NET 8 运行时。\n"
                    f"当前已安装运行时：\n{output}\n"
                    "请安装 .NET 8.0 Runtime (SDK 或 Desktop Runtime 均可)：\n"
                    "👉 https://dotnet.microsoft.com/en-us/download/dotnet/8.0"
                )

        except subprocess.CalledProcessError:
            raise RuntimeError("无法执行 'dotnet --list-runtimes'，请检查 .NET 安装是否损坏。")

    @classmethod
    def setup(cls):
        if cls._initialized: return

        # === 新增：先检查环境 ===
        cls._check_dotnet_installed()

        # 1. 定位 DLL 目录
        current_dir = Path(__file__).parent.absolute()
        dll_folder = current_dir / "lib"

        if not dll_folder.exists():
            # 开发环境 fallback
            # 假设你的开发目录结构是 src/osu_lib，上一级是根目录
            dev_path = current_dir.parent.parent / "osu-tools" / "published_output"
            if dev_path.exists():
                dll_folder = dev_path
            else:
                # 最后的 fallback，如果是在构建环境中
                pass

        if not dll_folder.exists():
            warnings.warn(f"Warning: DLL folder not found at {dll_folder}")

        # 2. 加入 sys.path
        sys.path.append(str(dll_folder))

        # 3. 显式加载 CoreCLR (针对 Linux/macOS 必须这一步)
        try:
            from pythonnet import load
            try:
                # 这一步至关重要，必须指定 coreclr 否则 Linux 会找 Mono
                load("coreclr")
            except Exception as e:
                # 如果 load("coreclr") 失败，说明 pythonnet 找不到 .NET Core
                raise RuntimeError(
                    f"【加载失败】Pythonnet 无法加载 CoreCLR。\n"
                    f"错误详情: {e}\n"
                    "请确保你安装的是 Linux 版本的 .NET 8，并且 dotnet 在 PATH 环境变量中。"
                )
        except ImportError:
            raise ImportError("Missing dependency: pythonnet")

        # 4. 现在才能安全导入 clr
        import clr
        import System
        if cls._initialized:
            return

        current_dir = Path(__file__).parent.absolute()
        # 候选路径 1: 包内自带的 lib 目录 (安装后的正常路径)
        local_lib = current_dir / "lib"

        # 候选路径 2: 开发环境的构建输出目录 (源码调试用)
        # 假设结构: root/src/osu_lib/calculator.py -> 回溯两级到 root -> osu-tools
        dev_lib = current_dir.parent.parent / "osu-tools" / "published_output"

        # 判定逻辑: 检查哪个目录下有核心文件 "osu.Game.dll"
        if (local_lib / "osu.Game.dll").exists():
            dll_folder = local_lib
        elif (dev_lib / "osu.Game.dll").exists():
            dll_folder = dev_lib
            print(f"DEBUG: 使用开发环境运行库: {dll_folder}")
        else:
            # 都找不到，还是指向 local_lib，让后面的逻辑报错(或者在这里直接报错)
            dll_folder = local_lib
            warnings.warn(f"【严重警告】在 {local_lib} 和 {dev_lib} 均未发现 osu.Game.dll，程序可能即将崩溃。")

        sys.path.append(str(dll_folder))

        # 4. 加载必要的 DLL 引用
        libs_to_load = [
            "osu.Framework.dll",
            "osu.Game.dll",
            "osu.Game.Rulesets.Osu.dll",
            "osu.Game.Rulesets.Taiko.dll",
            "osu.Game.Rulesets.Catch.dll",
            "osu.Game.Rulesets.Mania.dll",
        ]

        for lib in libs_to_load:
            path = dll_folder / lib
            if path.exists():
                try:
                    # 移除 .dll 后缀进行引用
                    clr.AddReference(str(path).replace('.dll', ''))
                except Exception as e:
                    warnings.warn(f"加载 {lib} 失败: {e}")
            else:
                warnings.warn(f"缺失文件: {lib}")

        cls._initialized = True


# ================= 核心计算类 =================

class OsuCalculator:
    def __init__(self):
        """
        初始化计算器。如果环境未配置，会自动调用 setup。
        """
        if not OsuEnvironment._initialized:
            OsuEnvironment.setup()

        # === 关键：在 DLL 加载后才导入 C# 模块 ===
        # 将 C# 类型保存在 self 中，避免污染全局命名空间，也防止 Import 错误
        import System
        from System.IO import FileStream, FileMode, FileAccess, FileShare
        from System.Collections.Generic import List

        # Beatmap & IO
        from osu.Game.Beatmaps.Formats import LegacyBeatmapDecoder
        from osu.Game.IO import LineBufferedReader
        from osu.Game.Beatmaps import FlatWorkingBeatmap

        # Rulesets
        from osu.Game.Rulesets.Osu import OsuRuleset
        from osu.Game.Rulesets.Taiko import TaikoRuleset
        from osu.Game.Rulesets.Catch import CatchRuleset
        from osu.Game.Rulesets.Mania import ManiaRuleset

        # Mods & Scoring
        from osu.Game.Rulesets.Mods import Mod
        from osu.Game.Scoring import ScoreInfo
        from osu.Game.Rulesets.Scoring import HitResult

        # Difficulty Attributes
        from osu.Game.Rulesets.Osu.Difficulty import OsuDifficultyAttributes
        from osu.Game.Rulesets.Taiko.Difficulty import TaikoDifficultyAttributes
        from osu.Game.Rulesets.Catch.Difficulty import CatchDifficultyAttributes
        from osu.Game.Rulesets.Mania.Difficulty import ManiaDifficultyAttributes

        # Catch Objects
        from osu.Game.Rulesets.Catch.Objects import Fruit, Droplet, TinyDroplet, JuiceStream

        # 保存引用到 self (或者作为模块级缓存，这里为了隔离性放在实例或类中)
        self.System = System
        self.FileStream = FileStream
        self.FileMode = FileMode
        self.FileAccess = FileAccess
        self.FileShare = FileShare
        self.List = List
        self.LegacyBeatmapDecoder = LegacyBeatmapDecoder
        self.LineBufferedReader = LineBufferedReader
        self.FlatWorkingBeatmap = FlatWorkingBeatmap
        self.HitResult = HitResult
        self.ScoreInfo = ScoreInfo
        self.Mod = Mod

        # 难度属性映射
        self.DiffAttrs = {
            0: OsuDifficultyAttributes,
            1: TaikoDifficultyAttributes,
            2: CatchDifficultyAttributes,
            3: ManiaDifficultyAttributes
        }

        # Catch 对象类型
        self.CatchObjects = {
            'Fruit': Fruit,
            'Droplet': Droplet,
            'TinyDroplet': TinyDroplet,
            'JuiceStream': JuiceStream
        }

        # 初始化规则集
        self.rulesets = {
            0: OsuRuleset(),
            1: TaikoRuleset(),
            2: CatchRuleset(),
            3: ManiaRuleset()
        }

    def _parse_mods(self, mod_list, ruleset):
        """
        将 Python 输入 (字符串列表 / 字典列表 / 对象列表) 转换为 C# Mod 列表。
        兼容以下格式：
        1. ["HD", "DT"]
        2. [{"acronym": "HD"}, {"acronym": "DT"}]  (常见 API 格式)
        3. [{"Acronym": "HD"}]                     (C# JSON 风格)
        4. [ModObj(acronym="HD")]                  (Pydantic/对象)
        """
        available_mods = ruleset.CreateAllMods()
        # 创建 C# List<Mod>
        csharp_mods = self.List[self.Mod]()

        if not mod_list:
            return csharp_mods

        for m in mod_list:
            target_acronym = None

            # === 1. 如果是字符串 (例如 "HD") ===
            if isinstance(m, str):
                target_acronym = m

            # === 2. 如果是字典 (例如 {"acronym": "DT"}) ===
            elif isinstance(m, dict):
                # 优先找 'acronym' (小写)，找不到再找 'Acronym' (大写)
                target_acronym = m.get("acronym") or m.get("Acronym")

                # 如果字典里连 acronym 都没有，可能是无效数据，跳过
                if target_acronym is None:
                    continue

            # === 3. 如果是对象 (例如 Pydantic model) ===
            else:
                # 尝试获取 .acronym 或 .Acronym 属性
                target_acronym = getattr(m, "acronym", None) or getattr(m, "Acronym", None)

            # 如果提取不出缩写字符串，跳过该项
            if not target_acronym:
                continue

            # === 4. 在 C# 提供的可用 Mod 中查找 ===
            # str(x.Acronym) 是 C# 里的缩写，转成 Python 字符串进行比对
            found = next(
                (x for x in available_mods if str(x.Acronym).upper() == str(target_acronym).upper()),
                None
            )

            if found:
                csharp_mods.Add(found)
            else:
                # 可选：打印警告，告知未找到该 Mod (例如 SV2 等特殊 Mod)
                # print(f"Warning: Mod '{target_acronym}' is not available in this ruleset.")
                pass

        return csharp_mods

    def _extract_stat(self, stats_obj, attr_name, default=0):
        """安全地从对象或字典中获取属性，用于兼容 Pydantic 和 Dict"""
        if stats_obj is None:
            return default
        # 尝试作为字典获取
        if isinstance(stats_obj, dict):
            return stats_obj.get(attr_name, default)
        # 尝试作为对象属性获取 (Pydantic)
        return getattr(stats_obj, attr_name, default)

    def _has_valid_stats(self, stats_obj):
        """检查统计数据是否包含非零的有效点击数"""
        if not stats_obj:
            return False
        # 检查关键字段是否有大于0的值
        keys = ['great', 'ok', 'meh', 'good', 'perfect', 'miss', 'large_tick_hit', 'small_tick_hit', 'small_tck_miss']
        for k in keys:
            if self._extract_stat(stats_obj, k) > 0:
                return True
        return False

    # ================= 模拟/填充逻辑更新 =================

    def _sim_osu(self, acc, beatmap, misses, stats_obj=None):
        """Standard: 优先使用 stats_obj，否则根据 acc 模拟"""

        # 1. 如果提供了详细数据，直接使用
        if self._has_valid_stats(stats_obj):
            return {
                self.HitResult.Great: self._extract_stat(stats_obj, 'great'),
                self.HitResult.Ok: self._extract_stat(stats_obj, 'ok'),
                self.HitResult.Meh: self._extract_stat(stats_obj, 'meh'),
                self.HitResult.Miss: self._extract_stat(stats_obj, 'miss')
            }

        # 2. 否则执行模拟逻辑 (Fallback)
        total = beatmap.HitObjects.Count
        relevant = total - misses
        accuracy = acc / 100.0
        n300, n100, n50 = 0, 0, 0

        if relevant <= 0: return {self.HitResult.Miss: misses}
        rel_acc = accuracy * total / relevant
        rel_acc = max(0.0, min(1.0, rel_acc))

        if rel_acc >= 0.25:
            ratio = math.pow(1 - (rel_acc - 0.25) / 0.75, 2)
            c100 = 6 * relevant * (1 - rel_acc) / (5 * ratio + 4)
            c50 = c100 * ratio
            n100 = int(round(c100))
            n50 = int(round(c100 + c50) - n100)
        elif rel_acc >= 1.0 / 6:
            c100 = 6 * relevant * rel_acc - relevant
            c50 = relevant - c100
            n100 = int(round(c100))
            n50 = int(round(c100 + c50) - n100)
        else:
            c50 = 6 * relevant * rel_acc
            n50 = int(round(c50))
            misses = total - n50
        n300 = total - n100 - n50 - misses

        return {
            self.HitResult.Great: max(0, n300),
            self.HitResult.Ok: max(0, n100),
            self.HitResult.Meh: max(0, n50),
            self.HitResult.Miss: max(0, misses)
        }

    def _sim_taiko(self, acc, beatmap, misses, stats_obj=None):
        """Taiko"""
        if self._has_valid_stats(stats_obj):
            return {
                self.HitResult.Great: self._extract_stat(stats_obj, 'great'),
                self.HitResult.Ok: self._extract_stat(stats_obj, 'ok'),  # Taiko 的 Good 通常对应 API 的 Ok
                self.HitResult.Miss: self._extract_stat(stats_obj, 'miss')
            }

        # Fallback Simulation
        total = beatmap.HitObjects.Count
        relevant = total - misses
        accuracy = acc / 100.0
        n_great = int(round((2 * accuracy - 1) * relevant))
        n_good = relevant - n_great

        return {
            self.HitResult.Great: max(0, n_great),
            self.HitResult.Ok: max(0, n_good),
            self.HitResult.Miss: max(0, misses)
        }

    def _sim_mania(self, acc, beatmap, misses, score_val, stats_obj=None):
        """Mania"""
        if self._has_valid_stats(stats_obj):
            return {
                self.HitResult.Perfect: self._extract_stat(stats_obj, 'perfect'),
                self.HitResult.Great: self._extract_stat(stats_obj, 'great'),
                self.HitResult.Good: self._extract_stat(stats_obj, 'good'),
                self.HitResult.Ok: self._extract_stat(stats_obj, 'ok'),
                self.HitResult.Meh: self._extract_stat(stats_obj, 'meh'),
                self.HitResult.Miss: self._extract_stat(stats_obj, 'miss')
            }
        total = beatmap.HitObjects.Count
        relevant = total - misses
        accuracy = acc / 100.0
        n_perfect, n_great, n_good, n_ok, n_meh = 0, 0, 0, 0, 0

        if relevant > 0:
            if accuracy >= 0.96:
                p = 1 - (1 - accuracy) / 0.04
                n_perfect = int(round(p * relevant))
                n_great = relevant - n_perfect
            elif accuracy >= 0.90:
                p = 1 - (0.96 - accuracy) / 0.06
                n_great = int(round(p * relevant))
                n_good = relevant - n_great
            elif accuracy >= 0.80:
                p = 1 - (0.90 - accuracy) / 0.10
                n_good = int(round(p * relevant))
                n_ok = relevant - n_good
            elif accuracy >= 0.60:
                p = 1 - (0.80 - accuracy) / 0.20
                n_ok = int(round(p * relevant))
                n_meh = relevant - n_ok
            else:
                n_meh = relevant

        return {
            self.HitResult.Perfect: max(0, n_perfect),
            self.HitResult.Great: max(0, n_great),
            self.HitResult.Good: max(0, n_good),
            self.HitResult.Ok: max(0, n_ok),
            self.HitResult.Meh: max(0, n_meh),
            self.HitResult.Miss: max(0, misses)
        }

    def _sim_catch(self, acc, beatmap, misses, stats_obj=None):
        """Catch"""
        # 1. 优先读取详细数据
        if self._has_valid_stats(stats_obj):
            # 映射 NewStatistics 到 HitResult
            return {
                self.HitResult.Great: self._extract_stat(stats_obj, 'great'),  # Fruits
                self.HitResult.LargeTickHit: self._extract_stat(stats_obj, 'large_tick_hit'),  # Droplets
                self.HitResult.SmallTickHit: self._extract_stat(stats_obj, 'small_tick_hit'),  # Tiny Droplets
                self.HitResult.SmallTickMiss: self._extract_stat(stats_obj, 'small_tick_miss'),
                self.HitResult.Miss: self._extract_stat(stats_obj, 'miss')
            }

        # 2. 模拟逻辑
        # ... [这里必须保留原本的 max_fruits 统计和数学反推逻辑] ...
        # 重新统计 Max Values 用于计算
        Fruit = self.CatchObjects['Fruit']
        Droplet = self.CatchObjects['Droplet']
        TinyDroplet = self.CatchObjects['TinyDroplet']
        JuiceStream = self.CatchObjects['JuiceStream']

        max_fruits = 0
        max_droplets_total = 0
        max_tiny_droplets = 0

        for h in beatmap.HitObjects:
            if isinstance(h, Fruit):
                max_fruits += 1
            elif isinstance(h, JuiceStream):
                for n in h.NestedHitObjects:
                    if isinstance(n, TinyDroplet):
                        max_tiny_droplets += 1
                        max_droplets_total += 1
                    elif isinstance(n, Droplet):
                        max_droplets_total += 1
                    elif isinstance(n, Fruit):
                        max_fruits += 1

        max_droplets = max_droplets_total - max_tiny_droplets
        max_combo = max_fruits + max_droplets

        # 简单的模拟实现
        count_droplets = max(0, max_droplets - misses)  # 假设 Miss 都是 Droplet Miss (简化)
        count_fruits = max_fruits  # 假设没 Miss Fruit
        count_tiny = max_tiny_droplets  # 假设全连

        return {
            self.HitResult.Great: count_fruits,
            self.HitResult.LargeTickHit: count_droplets,
            self.HitResult.SmallTickHit: count_tiny,
            self.HitResult.Miss: misses
        }

    def calculate(self, file_path, mode=0, mods=None, acc=100.0, combo=None, misses=0,
                  score_val=None, statistics=None):
        """
        :param statistics: Statistics 对象或字典。如果有值，将忽略 acc/misses 进行计算。
        """
        if mods is None: mods = []
        abs_path = os.path.abspath(file_path)

        if not os.path.exists(abs_path):
            return {"error": f"File not found: {abs_path}"}

        ruleset = self.rulesets.get(mode)
        if not ruleset: return {"error": "Invalid mode"}

        fs = None
        reader = None
        try:
            # 1. Load Beatmap
            fs = self.FileStream(abs_path, self.FileMode.Open, self.FileAccess.Read, self.FileShare.Read)
            reader = self.LineBufferedReader(fs)
            decoder = self.LegacyBeatmapDecoder()
            beatmap = decoder.Decode(reader)

            converter = ruleset.CreateBeatmapConverter(beatmap)
            if converter.CanConvert():
                beatmap = converter.Convert()
            working_beatmap = self.FlatWorkingBeatmap(beatmap)

            # 2. Mods & Difficulty
            csharp_mods = self._parse_mods(mods, ruleset)
            diff_calc = ruleset.CreateDifficultyCalculator(working_beatmap)
            diff_attr = diff_calc.Calculate(csharp_mods)  # 这里省略类型转换代码，同之前

            # 3. Hit Results (关键修改)
            stats = {}

            # 如果 statistics 有效，misses 应该从 statistics 里取，以保持一致性
            effective_misses = misses
            if self._has_valid_stats(statistics):
                effective_misses = self._extract_stat(statistics, 'Miss')

            if mode == 0:
                stats = self._sim_osu(acc, beatmap, effective_misses, statistics)
            elif mode == 1:
                stats = self._sim_taiko(acc, beatmap, effective_misses, statistics)
            elif mode == 2:
                stats = self._sim_catch(acc, beatmap, effective_misses, statistics)
            elif mode == 3:
                stats = self._sim_mania(acc, beatmap, effective_misses, score_val, statistics)
            # 4. Construct Score
            score = self.ScoreInfo()
            score.Ruleset = ruleset.RulesetInfo
            score.BeatmapInfo = working_beatmap.BeatmapInfo
            score.Mods = csharp_mods.ToArray()

            # 如果传了 Combo 用传的，否则用满 Combo
            score.MaxCombo = int(combo) if combo is not None else diff_attr.MaxCombo
            score.Accuracy = float(acc) / 100.0

            for result, count in stats.items():
                score.Statistics[result] = count

            # 5. Calculate PP
            perf_calc = ruleset.CreatePerformanceCalculator()
            pp_attr = perf_calc.Calculate(score, diff_attr)

            res = {
                "mode": mode,
                "stars": diff_attr.StarRating,
                "pp": pp_attr.Total,
                "max_combo": diff_attr.MaxCombo,
                # 为了调试方便，可以看到到底用了什么判定
                "stats_used": {str(k): v for k, v in stats.items()}
            }
            return res

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
        finally:
            if reader: reader.Dispose()
            if fs: fs.Dispose()
