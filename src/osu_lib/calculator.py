import sys
import os
import math
import warnings
import subprocess
import shutil
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Union, Optional, Any, Type


# ================= 数据结构定义 =================

@dataclass
class CalculationResult:
    """
    计算结果的数据类
    """
    mode: int = 0
    stars: float = 0.0
    pp: float = 0.0
    max_combo: int = 0
    # 实际参与计算的 HitResult 统计 (用于调试)
    stats_used: Dict[str, int] = field(default_factory=dict)
    # 如果发生错误，错误信息将存储在此，且上述数值可能无效
    error: Optional[str] = None

    @property
    def is_success(self) -> bool:
        """检查计算是否成功"""
        return self.error is None


# ================= 库配置与初始化 =================

class OsuEnvironment:
    """管理 .NET 运行时和 DLL 加载的单例类"""
    _initialized: bool = False

    @classmethod
    def _check_dotnet_installed(cls) -> None:
        """检查系统是否安装了 .NET 8 Runtime"""

        # 1. 检查 dotnet 命令
        # shutil.which 在 Python < 3.12 的 Windows 上不支持 Path 对象，强制转 str
        dotnet_cmd = "dotnet"
        if not shutil.which(str(dotnet_cmd)):
            # Windows fallback check
            if os.name == 'nt':
                program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
                default_path = Path(program_files) / "dotnet" / "dotnet.exe"
                if default_path.exists():
                    dotnet_cmd = str(default_path)
                else:
                    cls._raise_dotnet_error()
            else:
                cls._raise_dotnet_error()

        # 2. 检查 Runtime 版本
        try:
            # Windows 上隐藏 cmd 窗口
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                [dotnet_cmd, "--list-runtimes"],
                capture_output=True,
                text=True,
                check=True,
                startupinfo=startupinfo
            )

            if "Microsoft.NETCore.App 8." not in result.stdout:
                raise RuntimeError(
                    f"【版本错误】未检测到 .NET 8 Runtime。\n当前列表:\n{result.stdout}\n"
                    "请下载安装: https://dotnet.microsoft.com/en-us/download/dotnet/8.0"
                )

        except (subprocess.CalledProcessError, FileNotFoundError):
            raise RuntimeError("无法执行 dotnet 命令，请检查 .NET 8 是否正确安装。")

    @staticmethod
    def _raise_dotnet_error():
        raise RuntimeError(
            "【致命错误】未检测到 'dotnet' 命令。\n"
            "请安装 .NET 8 Runtime: https://dotnet.microsoft.com/en-us/download/dotnet/8.0"
        )

    @classmethod
    def setup(cls) -> None:
        if cls._initialized: return

        cls._check_dotnet_installed()

        # 1. 定位 DLL 目录 (合并了你原本代码中的重复逻辑)
        current_dir = Path(__file__).parent.absolute()
        local_lib = current_dir / "lib"
        # 假设结构: src/osu_lib/calculator.py -> osu-tools/published_output
        dev_lib = current_dir.parent.parent / "osu-tools" / "published_output"

        dll_folder: Path

        # 优先使用包内 lib，其次尝试开发目录，最后回退到 local_lib 报错
        if (local_lib / "osu.Game.dll").exists():
            dll_folder = local_lib
        elif (dev_lib / "osu.Game.dll").exists():
            dll_folder = dev_lib
            print(f"DEBUG: 使用开发环境运行库: {dll_folder}")
        else:
            dll_folder = local_lib
            warnings.warn(f"Warning: 核心 DLL 未在 {local_lib} 找到，功能可能失效。")

        if str(dll_folder) not in sys.path:
            sys.path.append(str(dll_folder))

        # 2. 加载运行时
        try:
            from pythonnet import load
            try:
                load("coreclr")
            except Exception as e:
                # 再次尝试或报错
                if "already loaded" not in str(e):
                    raise RuntimeError(f"Pythonnet 加载 CoreCLR 失败: {e}")
        except ImportError:
            raise ImportError("Missing dependency: pythonnet")

        import clr
        import System  # noqa: F401

        # 3. 加载 DLL
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
                    clr.AddReference(str(path).replace('.dll', ''))
                except Exception:
                    pass  # 忽略已加载或依赖错误
            else:
                pass  # 静默失败，calculate 时会报错

        cls._initialized = True


# ================= 核心计算类 =================

class OsuCalculator:
    def __init__(self):
        """
        初始化计算器。如果环境未配置，会自动调用 setup。
        """
        if not OsuEnvironment._initialized:
            OsuEnvironment.setup()

        # 延迟导入 C# 类型以避免模块加载时的错误
        import System
        from System.IO import FileStream, FileMode, FileAccess, FileShare
        from System.Collections.Generic import List as CsList

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

        # 绑定到实例
        self.System = System
        self.FileStream = FileStream
        self.FileMode = FileMode
        self.FileAccess = FileAccess
        self.FileShare = FileShare
        self.CsList = CsList  # 重命名避免冲突

        self.LegacyBeatmapDecoder = LegacyBeatmapDecoder
        self.LineBufferedReader = LineBufferedReader
        self.FlatWorkingBeatmap = FlatWorkingBeatmap

        self.HitResult = HitResult
        self.ScoreInfo = ScoreInfo
        self.Mod = Mod

        # Catch 对象类型
        self.CatchObjects = {
            'Fruit': Fruit,
            'Droplet': Droplet,
            'TinyDroplet': TinyDroplet,
            'JuiceStream': JuiceStream
        }

        # 初始化规则集
        self.rulesets: Dict[int, Any] = {
            0: OsuRuleset(),
            1: TaikoRuleset(),
            2: CatchRuleset(),
            3: ManiaRuleset()
        }

    def _parse_mods(self, mod_list: Union[List[str], List[Dict], List[Any]], ruleset: Any) -> Any:
        """
        将 Python 输入转换为 C# Mod 列表。
        :return: System.Collections.Generic.List<osu.Game.Rulesets.Mods.Mod>
        """
        available_mods = ruleset.CreateAllMods()
        csharp_mods = self.CsList[self.Mod]()

        if not mod_list:
            return csharp_mods

        for m in mod_list:
            target_acronym: Optional[str]

            if isinstance(m, str):
                target_acronym = m
            elif isinstance(m, dict):
                target_acronym = m.get("acronym") or m.get("Acronym")
            else:
                target_acronym = getattr(m, "acronym", None) or getattr(m, "Acronym", None)

            if not target_acronym:
                continue

            # 在 C# List 中查找
            found = next(
                (x for x in available_mods if str(x.Acronym).upper() == str(target_acronym).upper()),
                None
            )

            if found:
                csharp_mods.Add(found)

        return csharp_mods

    def _extract_stat(self, stats_obj: Union[Dict, Any, None], attr_name: str, default: int = 0) -> int:
        """安全提取统计属性"""
        if stats_obj is None:
            return default
        if isinstance(stats_obj, dict):
            # 支持 key 为 "Miss" 或 "miss"
            return stats_obj.get(attr_name, stats_obj.get(attr_name.capitalize(), default))
        return getattr(stats_obj, attr_name, default)

    def _has_valid_stats(self, stats_obj: Union[Dict, Any, None]) -> bool:
        """检查是否有有效统计数据"""
        if not stats_obj:
            return False
        keys = ['great', 'ok', 'meh', 'good', 'perfect', 'miss', 'large_tick_hit']
        for k in keys:
            if self._extract_stat(stats_obj, k) > 0:
                return True
        return False

    # ================= 模拟逻辑 (保持原有逻辑，仅添加类型提示) =================

    def _sim_osu(self, acc: float, beatmap: Any, misses: int, stats_obj: Any) -> Dict[Any, int]:
        if self._has_valid_stats(stats_obj):
            return {
                self.HitResult.Great: self._extract_stat(stats_obj, 'great'),
                self.HitResult.Ok: self._extract_stat(stats_obj, 'ok'),
                self.HitResult.Meh: self._extract_stat(stats_obj, 'meh'),
                self.HitResult.Miss: self._extract_stat(stats_obj, 'miss'),
                self.HitResult.SliderTailHit: self._extract_stat(stats_obj, 'slider_tail_hit'),
                self.HitResult.LargeTickHit: self._extract_stat(stats_obj, 'large_tick_hit'),
                self.HitResult.SmallTickHit: self._extract_stat(stats_obj, 'small_tick_hit'),
                self.HitResult.SmallTickMiss: self._extract_stat(stats_obj, 'small_tick_miss')
            }

        # Fallback 模拟
        total = beatmap.HitObjects.Count
        relevant = total - misses
        accuracy = acc / 100.0
        n300, n100, n50 = 0, 0, 0

        if relevant <= 0: return {self.HitResult.Miss: misses}
        rel_acc = max(0.0, min(1.0, accuracy * total / relevant))

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

    def _sim_taiko(self, acc: float, beatmap: Any, misses: int, stats_obj: Any) -> Dict[Any, int]:
        if self._has_valid_stats(stats_obj):
            return {
                self.HitResult.Great: self._extract_stat(stats_obj, 'great'),
                self.HitResult.Ok: self._extract_stat(stats_obj, 'ok'),
                self.HitResult.Miss: self._extract_stat(stats_obj, 'miss')
            }

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

    def _sim_mania(self, acc: float, beatmap: Any, misses: int, stats_obj: Any) -> Dict[Any, int]:
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

    def _sim_catch(self, acc: float, beatmap: Any, misses: int, stats_obj: Any) -> Dict[Any, int]:
        if self._has_valid_stats(stats_obj):
            return {
                self.HitResult.Great: self._extract_stat(stats_obj, 'great'),
                self.HitResult.LargeTickHit: self._extract_stat(stats_obj, 'large_tick_hit'),
                self.HitResult.SmallTickHit: self._extract_stat(stats_obj, 'small_tick_hit'),
                self.HitResult.SmallTickMiss: self._extract_stat(stats_obj, 'small_tick_miss'),
                self.HitResult.Miss: self._extract_stat(stats_obj, 'miss')
            }

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
        count_droplets = max(0, max_droplets - misses)

        return {
            self.HitResult.Great: max_fruits,
            self.HitResult.LargeTickHit: count_droplets,
            self.HitResult.SmallTickHit: max_tiny_droplets,
            self.HitResult.Miss: misses
        }

    # ================= 主计算函数 =================

    def calculate(
            self,
            file_path: str,
            mode: int = 0,
            mods: Optional[List[Union[str, Dict[str, Any], Any]]] = None,
            acc: float = 100.0,
            combo: Optional[int] = None,
            misses: int = 0,
            legacy_total_score: Optional[int] = None,
            statistics: Optional[Union[Dict[str, int], Any]] = None
    ) -> CalculationResult:
        """
        计算 PP 和 Star Rating。

        :param file_path: .osu 谱面文件路径
        :param mode: 0=Osu, 1=Taiko, 2=Catch, 3=Mania
        :param mods: Mod 列表，支持 ["HD"] 或 [{"acronym": "HD"}]
        :param acc: 准确率 (0-100)，如果 statistics 有值则此参数在 Standard 模式下可能被忽略
        :param combo: 最大连击数
        :param misses: Miss 数量 (如果 statistics 有值则优先使用 statistics 里的 miss)
        :param legacy_total_score: 传统总分。>0 时会触发 osu!stable 兼容模式 (Legacy Mode)
        :param statistics: 详细统计数据 (dict 或 object)，如 {'great': 300, 'ok': 10}
        :return: CalculationResult 对象
        """
        if mods is None: mods = []
        abs_path = os.path.abspath(file_path)

        if not os.path.exists(abs_path):
            return CalculationResult(error=f"File not found: {abs_path}")

        ruleset = self.rulesets.get(mode)
        if not ruleset:
            return CalculationResult(error=f"Invalid mode: {mode}")

        fs = None
        reader = None
        try:
            # 1. 加载谱面
            fs = self.FileStream(abs_path, self.FileMode.Open, self.FileAccess.Read, self.FileShare.Read)
            reader = self.LineBufferedReader(fs)
            decoder = self.LegacyBeatmapDecoder()
            beatmap = decoder.Decode(reader)

            converter = ruleset.CreateBeatmapConverter(beatmap)
            if converter.CanConvert():
                beatmap = converter.Convert()
            working_beatmap = self.FlatWorkingBeatmap(beatmap)

            # 2. Mod 解析与难度计算
            csharp_mods = self._parse_mods(mods, ruleset)
            diff_calc = ruleset.CreateDifficultyCalculator(working_beatmap)
            diff_attr = diff_calc.Calculate(csharp_mods)

            # 3. Hit Results 填充
            stats: Dict[Any, int] = {}

            effective_misses = misses
            if self._has_valid_stats(statistics):
                effective_misses = self._extract_stat(statistics, 'miss')

            if mode == 0:
                stats = self._sim_osu(acc, beatmap, effective_misses, statistics)
            elif mode == 1:
                stats = self._sim_taiko(acc, beatmap, effective_misses, statistics)
            elif mode == 2:
                stats = self._sim_catch(acc, beatmap, effective_misses, statistics)
            elif mode == 3:
                stats = self._sim_mania(acc, beatmap, effective_misses, statistics)

            # 4. 构造 ScoreInfo
            score = self.ScoreInfo()
            score.Ruleset = ruleset.RulesetInfo
            score.BeatmapInfo = working_beatmap.BeatmapInfo
            score.Mods = csharp_mods.ToArray()

            # 设置 Legacy Score 以启用 Stable 物理/判定逻辑
            score.LegacyTotalScore = int(legacy_total_score) if legacy_total_score is not None and int(
                legacy_total_score) > 0 else 0

            score.MaxCombo = int(combo) if combo is not None else diff_attr.MaxCombo
            score.Accuracy = float(acc) / 100.0

            for result, count in stats.items():
                if count > 0:
                    score.Statistics[result] = count

            # 5. 计算 PP
            perf_calc = ruleset.CreatePerformanceCalculator()
            pp_attr = perf_calc.Calculate(score, diff_attr)

            # 6. 返回结构化数据
            # 将 C# 的 HitResult 枚举转为字符串，方便调试查看
            stats_readable = {str(k): v for k, v in stats.items()}

            return CalculationResult(
                mode=mode,
                stars=diff_attr.StarRating,
                pp=pp_attr.Total,
                max_combo=diff_attr.MaxCombo,
                stats_used=stats_readable
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return CalculationResult(error=str(e))
        finally:
            if reader: reader.Dispose()
            if fs: fs.Dispose()
