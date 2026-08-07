"""
PPT 大纲 Schema

结构化大纲模型 + 结构约束自动修复（设计方案 §4.4）：
- 首页必须 cover（缺失时自动插入，用大纲 title/subtitle）
- 必须含 content 页（无法自动生成，抛错走重试/降级）
- summary 必须在最后（自动移动到末尾并移除中间重复）
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class PPTSlide(BaseModel):
    """单页幻灯片"""
    type: Literal["cover", "agenda", "section", "content", "summary"]
    title: str
    subtitle: Optional[str] = None       # cover / section 用
    items: Optional[List[str]] = None     # agenda 目录项
    bullets: Optional[List[str]] = None   # content 要点
    code: Optional[str] = None            # content 代码块
    notes: Optional[str] = None           # 演讲者备注


class PPTOutline(BaseModel):
    """PPT 大纲（生成管线中间产物）"""
    title: str
    subtitle: str = ""
    style: Literal["business", "academic", "minimal"] = "business"
    # 注意：min_length 校验放在 validate_structure 内（自动插封面之后再校验），
    # 否则字段层约束先于 after validator 执行，2 页输入会被直接拒绝、
    # 「自动插封面」的修复逻辑没有机会运行
    slides: List[PPTSlide] = Field(max_length=20)

    @model_validator(mode="after")
    def validate_structure(self):
        """结构约束：首页必须封面、必须含内容页、总结页必须在最后、页数 ≥3。

        采用自动修复而非抛错（§4.4）——避免二次调用 LLM，保证确定性；
        仅「缺少 content 页」「修复后仍不足 3 页」抛错（无法自动生成内容），
        由调用方重试/降级。
        """
        types = [s.type for s in self.slides]

        # ① 首页不是 cover → 自动在最前面插入封面（用大纲 title/subtitle）
        if not types or types[0] != "cover":
            self.slides.insert(0, PPTSlide(
                type="cover", title=self.title, subtitle=self.subtitle))

        # ② 缺少 content → 抛错走重试/降级（无法自动生成内容）
        if "content" not in [s.type for s in self.slides]:
            raise ValueError("大纲至少需要包含一个内容页")

        # ③ summary 不在最后 → 移到末尾（并移除中间的重复 summary）
        summaries = [s for s in self.slides if s.type == "summary"]
        self.slides = [s for s in self.slides if s.type != "summary"] + summaries

        # ④ 修复后页数仍不足（封面 + 内容页 + 总结页 的最小结构）
        if len(self.slides) < 3:
            raise ValueError("大纲页数不足（至少需要封面、内容页与总结页）")
        return self
