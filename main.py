import sys
import os
import math
from pathlib import Path
import warnings


# ================= 库配置与初始化 =================

class OsuEnvironment:
    """管理 .NET 运行时和 DLL 加载的单例类"""
    _initialized = False
    _dll_folder = None

    @classmethod
    def setup(cls, dll_folder_path: str = None, dotnet_root: str = None):
        """
        初始化 .NET 环境和加载 osu! DLL。
        :param dll_folder_path: osu-tools publish 后的文件夹路径
        :param dotnet_root: .NET 8 运行时的路径 (可选)
        """
        if cls._initialized:
            return

        # 1. 设置 DLL 路径
        if dll_folder_path:
            cls._dll_folder = Path(dll_folder_path)
        else:
            # 获取当前脚本所在的目录
            current_dir = Path(__file__).parent.absolute()
            # 假设 DLL 都在同级的 lib 文件夹下
            cls._dll_folder = current_dir / "lib"

        if not cls._dll_folder.exists():
            # 兼容开发环境：如果包内没有，尝试找上一级目录的 compiled_output (本地调试用)
            dev_path = Path("osu-tools/published_output")
            if dev_path.exists():
                cls._dll_folder = dev_path
            else:
                raise FileNotFoundError(f"找不到 DLL 目录: {cls._dll_folder}")

        # 2. 将 DLL 目录加入 sys.path 以便 pythonnet 查找
        sys.path.append(str(cls._dll_folder))

        # 3. 加载 Pythonnet Runtime (CoreCLR)
        try:
            from pythonnet import load
            # 如果尚未加载运行时，尝试加载
            # 注意：如果其他库已经加载了运行时，这里可能会抛出警告或忽略
            try:
                load("coreclr")
            except Exception:
                pass  # 运行时可能已被加载，继续尝试
        except ImportError:
            raise ImportError("请先安装 pythonnet: pip install pythonnet")

        import clr
        import System

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
            path = cls._dll_folder / lib
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
    def __init__(self, dll_path=None):
        """
        初始化计算器。如果环境未配置，会自动调用 setup。
        """
        if not OsuEnvironment._initialized:
            OsuEnvironment.setup(dll_path)

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
        """将 Python 字符串列表转换为 C# Mod 列表"""
        available_mods = ruleset.CreateAllMods()
        csharp_mods = self.List[self.Mod]()  # 泛型列表初始化

        if not mod_list:
            return csharp_mods

        for m in mod_list:
            # 忽略大小写查找
            found = next((x for x in available_mods if str(x.Acronym).upper() == str(m).upper()), None)
            if found:
                csharp_mods.Add(found)
            else:
                print(f"Warning: Mod '{m}' not found.")
        return csharp_mods

    # ... [保留原本的模拟算法 _sim_osu, _sim_taiko 等] ...
    # 为了节省篇幅，这里假设 _sim_osu 等函数逻辑与你提供的一致
    # 只需要注意将 HitResult.Great 改为 self.HitResult.Great

    def _sim_osu(self, acc, beatmap, misses, count_good, count_meh):
        total = beatmap.HitObjects.Count
        relevant = total - misses
        accuracy = acc / 100.0
        n300, n100, n50 = 0, 0, 0

        if count_good is not None or count_meh is not None:
            n100 = count_good if count_good else 0
            n50 = count_meh if count_meh else 0
            n300 = total - n100 - n50 - misses
        else:
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

    def _sim_taiko(self, acc, beatmap, misses, count_good):
        total = beatmap.HitObjects.Count
        relevant = total - misses
        accuracy = acc / 100.0

        if count_good is not None:
            n_good = count_good
            n_great = total - n_good - misses
        else:
            n_great = int(round((2 * accuracy - 1) * relevant))
            n_good = relevant - n_great

        return {
            self.HitResult.Great: max(0, n_great),
            self.HitResult.Ok: max(0, n_good),
            self.HitResult.Miss: max(0, misses)
        }

    def _sim_mania(self, acc, beatmap, misses, score_val):
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

    def _sim_catch(self, acc, beatmap, misses, count_droplets_hit, count_tiny_hit):
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
        accuracy = acc / 100.0

        if count_droplets_hit is not None:
            count_droplets = count_droplets_hit
        else:
            count_droplets = max(0, max_droplets - misses)

        missed_droplets = max_droplets - count_droplets
        missed_fruits = misses - missed_droplets
        count_fruits = max(0, max_fruits - missed_fruits)

        if count_tiny_hit is not None:
            count_tiny_droplets = count_tiny_hit
        else:
            total_objects = max_combo + max_tiny_droplets
            target_total_hits = int(round(accuracy * total_objects))
            count_tiny_droplets = target_total_hits - count_fruits - count_droplets

        count_tiny_droplets = max(0, min(count_tiny_droplets, max_tiny_droplets))
        count_tiny_misses = max_tiny_droplets - count_tiny_droplets

        return {
            self.HitResult.Great: count_fruits,
            self.HitResult.LargeTickHit: count_droplets,
            self.HitResult.SmallTickHit: count_tiny_droplets,
            self.HitResult.SmallTickMiss: count_tiny_misses,
            self.HitResult.Miss: misses
        }

    def calculate(self, file_path, mode=0, mods=None, acc=100.0, combo=None, misses=0,
                  goods=None, mehs=None, score_val=None):
        """
        计算 PP 和 SR。
        :return: 字典包含结果，若出错则包含 error 字段
        """
        if mods is None: mods = []
        abs_path = os.path.abspath(file_path)

        if not os.path.exists(abs_path):
            raise FileNotFoundError(f"Beatmap file not found: {abs_path}")

        if mode not in self.rulesets:
            raise ValueError(f"Invalid mode: {mode}")

        ruleset = self.rulesets[mode]
        fs = None
        reader = None

        try:
            # 1. 读取谱面
            fs = self.FileStream(abs_path, self.FileMode.Open, self.FileAccess.Read, self.FileShare.Read)
            reader = self.LineBufferedReader(fs)
            decoder = self.LegacyBeatmapDecoder()
            beatmap = decoder.Decode(reader)

            # 2. 模式转换
            converter = ruleset.CreateBeatmapConverter(beatmap)
            if converter.CanConvert():
                beatmap = converter.Convert()

            working_beatmap = self.FlatWorkingBeatmap(beatmap)

            # 3. 处理 Mods
            csharp_mods = self._parse_mods(mods, ruleset)

            # 4. 计算 SR (Difficulty)
            diff_calc = ruleset.CreateDifficultyCalculator(working_beatmap)
            diff_attr_base = diff_calc.Calculate(csharp_mods)

            # 类型安全转换
            target_attr_type = self.DiffAttrs.get(mode)
            diff_attr = diff_attr_base
            extra_info = {}

            if mode == 0:
                # Standard 特殊处理 AR/OD
                if isinstance(diff_attr_base, target_attr_type):
                    extra_info = {"ar": beatmap.Difficulty.ApproachRate, "od": beatmap.Difficulty.OverallDifficulty}
                else:
                    diff_attr = target_attr_type(diff_attr_base)
            else:
                # 其他模式强制转换
                if not isinstance(diff_attr_base, target_attr_type):
                    diff_attr = target_attr_type(diff_attr_base)

            # 5. 生成 HitResults (模拟 Accuracy)
            stats = {}
            if mode == 0:
                stats = self._sim_osu(acc, beatmap, misses, goods, mehs)
            elif mode == 1:
                stats = self._sim_taiko(acc, beatmap, misses, goods)
            elif mode == 2:
                stats = self._sim_catch(acc, beatmap, misses, goods, mehs)  # goods/mehs 在 catch 中复用为 droplets
            elif mode == 3:
                stats = self._sim_mania(acc, beatmap, misses, score_val)

            # 6. 构造 ScoreInfo
            score = self.ScoreInfo()
            score.Ruleset = ruleset.RulesetInfo
            score.BeatmapInfo = working_beatmap.BeatmapInfo
            score.Mods = csharp_mods.ToArray()
            score.MaxCombo = int(combo) if combo is not None else diff_attr.MaxCombo
            score.Accuracy = float(acc) / 100.0

            # 填充统计数据
            for result, count in stats.items():
                score.Statistics[result] = count

            # 7. 计算 PP
            perf_calc = ruleset.CreatePerformanceCalculator()
            pp_attr = perf_calc.Calculate(score, diff_attr)

            res = {
                "mode": mode,
                "title": beatmap.Metadata.Title if beatmap.Metadata else "Unknown",
                "artist": beatmap.Metadata.Artist if beatmap.Metadata else "Unknown",
                "version": beatmap.Metadata.Author.Username if beatmap.Metadata else "",  # Diff Name
                "stars": diff_attr.StarRating,
                "pp": pp_attr.Total,
                "max_combo_map": diff_attr.MaxCombo,
                "stats": {str(k): v for k, v in stats.items()}
            }
            res.update(extra_info)
            return res

        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
        finally:
            # 资源清理
            if reader: reader.Dispose()
            if fs: fs.Dispose()