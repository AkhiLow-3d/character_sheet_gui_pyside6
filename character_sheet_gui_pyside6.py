from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageQt
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QSplitter,
    QTextEdit,
    QToolBar,
    QVBoxLayout,
    QWidget,
)


logger = logging.getLogger(__name__)


# ==========================================================
# Character Sheet Generator Core
# ==========================================================


@dataclass
class Theme:
    canvas_bg: Tuple[int, int, int] = (210, 210, 210)
    panel_bg: Tuple[int, int, int] = (181, 237, 226)
    border: Tuple[int, int, int] = (0, 0, 0)
    text: Tuple[int, int, int] = (0, 0, 0)
    border_width: int = 4
    padding: int = 18


@dataclass
class Layout:
    width: int = 1600
    height: int = 900
    margin: int = 28
    gap: int = 28
    left_ratio: float = 0.32
    center_ratio: float = 0.32
    right_ratio: float = 0.32
    left_top_h: int = 130
    left_mid_h: int = 80
    right_top_h: int = 95
    right_bottom_h: int = 215


@dataclass
class ImagePlacement:
    path: Optional[str] = None
    zoom_percent: int = 100
    offset_x: int = 0
    offset_y: int = 0


@dataclass
class CharacterData:
    title: str = "キャラクター名"
    profile_title: str = "設定"
    story_title: str = "ストーリー"
    profile_lines: List[str] = field(default_factory=lambda: [
        "名前：",
        "年齢：",
        "誕生日：",
        "身長：",
        "性格：",
        "好き：",
        "苦手：",
        "特技：",
        "一人称：",
    ])
    story_text: str = "ここにストーリーを入力してください。"
    main_image: ImagePlacement = field(default_factory=ImagePlacement)
    sub_image: ImagePlacement = field(default_factory=ImagePlacement)


@dataclass
class AppState:
    data: CharacterData = field(default_factory=CharacterData)
    theme: Theme = field(default_factory=Theme)
    layout: Layout = field(default_factory=Layout)
    font_path: Optional[str] = None


DEFAULT_JSON_EXAMPLE = {
    "title": "星屑機工士 レン",
    "profile_title": "設定",
    "story_title": "ストーリー",
    "profile_lines": [
        "名前：レン・アステル",
        "年齢：19歳",
        "誕生日：7月14日",
        "身長：168cm",
        "性格：無口だけど観察力が高い",
        "好き：古い機械、夜空、炭酸飲料",
        "苦手：人混み、暑さ",
        "特技：分解修理、即席改造",
        "一人称：僕",
    ],
    "story_text": "空に浮かぶ廃都で、壊れた観測機を直しながら暮らす少年。ある日、星の軌道を記録した禁制装置を拾ったことで、都市の封印された歴史に巻き込まれていく。失われた航路図を追う旅のなかで、仲間と出会い、自分が守るべきものを知っていく。",
    "main_image_path": "main.png",
    "sub_image_path": "sub.png",
}


def load_font(size: int, font_path: Optional[str] = None) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if font_path:
        candidates.append(font_path)

    candidates += [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
    ]

    for path in candidates:
        if path and os.path.exists(path):
            try:
                return ImageFont.truetype(path, size=size)
            except Exception as e:
                logger.warning("Failed to load font: %s (%s)", path, e)

    return ImageFont.load_default()


def draw_panel(draw: ImageDraw.ImageDraw, box: Tuple[int, int, int, int], theme: Theme) -> None:
    draw.rectangle(box, fill=theme.panel_bg, outline=theme.border, width=theme.border_width)


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, spacing: int = 8) -> Tuple[int, int]:
    b = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    return b[2] - b[0], b[3] - b[1]


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if not text:
        return ""

    lines: List[str] = []
    for paragraph in text.splitlines() or [text]:
        if not paragraph.strip():
            lines.append("")
            continue

        current = ""
        for ch in paragraph:
            test = current + ch
            w = draw.textbbox((0, 0), test, font=font)[2]
            if w <= max_width or not current:
                current = test
            else:
                lines.append(current)
                current = ch
        if current:
            lines.append(current)

    return "\n".join(lines)


def fit_image_with_placement(img: Image.Image, target_w: int, target_h: int, placement: ImagePlacement) -> Image.Image:
    img = img.convert("RGB")
    src_w, src_h = img.size
    base_scale = max(target_w / src_w, target_h / src_h)
    zoom = max(0.05, placement.zoom_percent / 100.0)
    scale = base_scale * zoom

    new_w = max(1, int(src_w * scale))
    new_h = max(1, int(src_h * scale))
    img = img.resize((new_w, new_h), Image.LANCZOS)

    center_x = new_w // 2 + placement.offset_x
    center_y = new_h // 2 + placement.offset_y

    left = center_x - target_w // 2
    top = center_y - target_h // 2

    left = max(0, min(left, max(0, new_w - target_w)))
    top = max(0, min(top, max(0, new_h - target_h)))

    right = left + target_w
    bottom = top + target_h

    return img.crop((left, top, right, bottom))


def draw_text_block(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    padding: int,
    line_spacing: int = 10,
    shrink_to_fit: bool = False,
    min_font_size: int = 14,
    font_path: Optional[str] = None,
) -> None:
    x1, y1, x2, y2 = box
    max_w = max(10, x2 - x1 - padding * 2)
    max_h = max(10, y2 - y1 - padding * 2)

    use_font = font
    wrapped = wrap_text(draw, text, use_font, max_w)

    if shrink_to_fit and hasattr(font, "size"):
        current_size = getattr(font, "size", 26)
        while current_size > min_font_size:
            tw, th = text_bbox(draw, wrapped, use_font, spacing=line_spacing)
            if th <= max_h:
                break
            current_size -= 1
            use_font = load_font(current_size, font_path)
            wrapped = wrap_text(draw, text, use_font, max_w)

    draw.multiline_text(
        (x1 + padding, y1 + padding),
        wrapped,
        font=use_font,
        fill=fill,
        spacing=line_spacing,
    )


def paste_image_panel(
    canvas: Image.Image,
    box: Tuple[int, int, int, int],
    placement: ImagePlacement,
    theme: Theme,
    placeholder: str,
    font: ImageFont.ImageFont,
) -> None:
    draw = ImageDraw.Draw(canvas)
    draw_panel(draw, box, theme)

    x1, y1, x2, y2 = box
    inner = (x1 + theme.padding, y1 + theme.padding, x2 - theme.padding, y2 - theme.padding)
    iw = max(1, inner[2] - inner[0])
    ih = max(1, inner[3] - inner[1])

    if placement.path and os.path.exists(placement.path):
        try:
            with Image.open(placement.path) as src_img:
                img = src_img.copy()
            img = fit_image_with_placement(img, iw, ih, placement)
            canvas.paste(img, (inner[0], inner[1]))
            return
        except Exception as e:
            logger.warning("Failed to load image: %s (%s)", placement.path, e)

    placeholder_text = wrap_text(draw, placeholder, font, max(10, iw - 20))
    tw, th = text_bbox(draw, placeholder_text, font)
    tx = inner[0] + max(0, (iw - tw) // 2)
    ty = inner[1] + max(0, (ih - th) // 2)
    draw.multiline_text((tx, ty), placeholder_text, font=font, fill=theme.text, spacing=8)


def generate_character_sheet_image(
    state: AppState,
    preview_scale: float = 1.0,
) -> Image.Image:
    layout = state.layout
    theme = state.theme
    data = state.data

    width = max(200, int(layout.width * preview_scale))
    height = max(200, int(layout.height * preview_scale))

    scaled_layout = Layout(
        width=width,
        height=height,
        margin=max(4, int(layout.margin * preview_scale)),
        gap=max(4, int(layout.gap * preview_scale)),
        left_ratio=layout.left_ratio,
        center_ratio=layout.center_ratio,
        right_ratio=layout.right_ratio,
        left_top_h=max(24, int(layout.left_top_h * preview_scale)),
        left_mid_h=max(20, int(layout.left_mid_h * preview_scale)),
        right_top_h=max(20, int(layout.right_top_h * preview_scale)),
        right_bottom_h=max(40, int(layout.right_bottom_h * preview_scale)),
    )

    scaled_theme = Theme(
        canvas_bg=theme.canvas_bg,
        panel_bg=theme.panel_bg,
        border=theme.border,
        text=theme.text,
        border_width=max(1, int(theme.border_width * preview_scale)),
        padding=max(6, int(theme.padding * preview_scale)),
    )

    canvas = Image.new("RGB", (scaled_layout.width, scaled_layout.height), scaled_theme.canvas_bg)
    draw = ImageDraw.Draw(canvas)

    title_font = load_font(max(16, int(48 * preview_scale)), state.font_path)
    section_title_font = load_font(max(12, int(34 * preview_scale)), state.font_path)
    body_font = load_font(max(11, int(26 * preview_scale)), state.font_path)
    placeholder_font = load_font(max(12, int(34 * preview_scale)), state.font_path)

    m = scaled_layout.margin
    g = scaled_layout.gap
    cw = scaled_layout.width - 2 * m
    ch = scaled_layout.height - 2 * m

    left_w = int(cw * scaled_layout.left_ratio)
    center_w = int(cw * scaled_layout.center_ratio)
    right_w = cw - left_w - center_w - 2 * g

    left_x1 = m
    left_x2 = left_x1 + left_w
    center_x1 = left_x2 + g
    center_x2 = center_x1 + center_w
    right_x1 = center_x2 + g
    right_x2 = right_x1 + right_w

    top_y = m
    bottom_y = m + ch

    left_title_box = (left_x1, top_y, left_x2, top_y + scaled_layout.left_top_h)
    left_mid_box = (left_x1, left_title_box[3] + g // 2, left_x2, left_title_box[3] + g // 2 + scaled_layout.left_mid_h)
    left_body_box = (left_x1, left_mid_box[3] + g // 2, left_x2, bottom_y)

    center_box = (center_x1, top_y, center_x2, bottom_y)

    right_top_box = (right_x1, top_y, right_x2, top_y + scaled_layout.right_top_h)
    right_bottom_box = (right_x1, bottom_y - scaled_layout.right_bottom_h, right_x2, bottom_y)
    right_story_box = (right_x1, right_top_box[3] + g // 2, right_x2, right_bottom_box[1] - g // 2)

    for box in [left_title_box, left_mid_box, left_body_box, right_top_box, right_story_box, right_bottom_box]:
        draw_panel(draw, box, scaled_theme)

    paste_image_panel(canvas, center_box, data.main_image, scaled_theme, "Main Image", placeholder_font)
    paste_image_panel(canvas, right_bottom_box, data.sub_image, scaled_theme, "Sub Image", placeholder_font)

    draw_text_block(
        draw, left_title_box, data.title, title_font, scaled_theme.text,
        scaled_theme.padding, 10, True, 14, state.font_path
    )
    draw_text_block(
        draw, left_mid_box, data.profile_title, section_title_font, scaled_theme.text,
        scaled_theme.padding, 8, True, 12, state.font_path
    )
    draw_text_block(
        draw, right_top_box, data.story_title, section_title_font, scaled_theme.text,
        scaled_theme.padding, 8, True, 12, state.font_path
    )

    profile_text = "\n".join(data.profile_lines)
    draw_text_block(
        draw, left_body_box, profile_text, body_font, scaled_theme.text,
        scaled_theme.padding, 10, True, 11, state.font_path
    )
    draw_text_block(
        draw, right_story_box, data.story_text, body_font, scaled_theme.text,
        scaled_theme.padding, 10, True, 11, state.font_path
    )

    return canvas


def save_character_sheet(state: AppState, out_path: str) -> str:
    image = generate_character_sheet_image(state, preview_scale=1.0)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    image.save(out_path)
    return out_path


def state_to_json_dict(state: AppState) -> dict:
    return {
        "title": state.data.title,
        "profile_title": state.data.profile_title,
        "story_title": state.data.story_title,
        "profile_lines": state.data.profile_lines,
        "story_text": state.data.story_text,
        "main_image_path": state.data.main_image.path,
        "sub_image_path": state.data.sub_image.path,
        "main_image": asdict(state.data.main_image),
        "sub_image": asdict(state.data.sub_image),
        "theme": asdict(state.theme),
        "layout": asdict(state.layout),
        "font_path": state.font_path,
    }


def state_from_json_dict(raw: dict) -> AppState:
    data = CharacterData(
        title=raw.get("title", "キャラクター名"),
        profile_title=raw.get("profile_title", "設定"),
        story_title=raw.get("story_title", "ストーリー"),
        profile_lines=raw.get("profile_lines", []),
        story_text=raw.get("story_text", ""),
    )

    main_raw = raw.get("main_image")
    sub_raw = raw.get("sub_image")

    if main_raw:
        data.main_image = ImagePlacement(**main_raw)
    else:
        data.main_image.path = raw.get("main_image_path")

    if sub_raw:
        data.sub_image = ImagePlacement(**sub_raw)
    else:
        data.sub_image.path = raw.get("sub_image_path")

    theme = Theme(**raw.get("theme", {})) if raw.get("theme") else Theme()
    layout = Layout(**raw.get("layout", {})) if raw.get("layout") else Layout()
    font_path = raw.get("font_path")

    return AppState(data=data, theme=theme, layout=layout, font_path=font_path)


# ==========================================================
# GUI
# ==========================================================


class ColorButton(QPushButton):
    def __init__(self, text: str, initial_rgb: Tuple[int, int, int], parent=None):
        super().__init__(text, parent)
        self.label_text = text
        self.rgb = initial_rgb
        self.clicked.connect(self.pick_color)
        self.refresh_style()

    def pick_color(self):
        color = QColorDialog.getColor(QColor(*self.rgb), self.window(), "色を選択")
        if color.isValid():
            self.rgb = (color.red(), color.green(), color.blue())
            self.refresh_style()
            if hasattr(self.window(), "schedule_preview_update"):
                self.window().schedule_preview_update()

    def set_rgb(self, rgb: Tuple[int, int, int]):
        self.rgb = tuple(rgb)
        self.refresh_style()

    def refresh_style(self):
        self.setText(f"{self.label_text}: {self.rgb}")
        r, g, b = self.rgb
        self.setStyleSheet(
            f"QPushButton {{ background-color: rgb({r}, {g}, {b}); border: 1px solid #666; padding: 6px; }}"
        )


class PreviewLabel(QLabel):
    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setStyleSheet("background: #222; border: 1px solid #555;")
        self._pixmap: Optional[QPixmap] = None

    def set_preview_pixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        self._refresh_scaled()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh_scaled()

    def _refresh_scaled(self):
        if not self._pixmap:
            return
        scaled = self._pixmap.scaled(
            self.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.setPixmap(scaled)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Character Sheet GUI Generator")
        self.resize(1600, 980)

        self.state = AppState()
        self.current_json_path: Optional[str] = None
        self._updating_ui = False
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.timeout.connect(self.refresh_preview)

        self.build_ui()
        self.load_default_example()
        self.refresh_ui_from_state()
        self.schedule_preview_update()

    # ------------------------------
    # UI Build
    # ------------------------------
    def build_ui(self):
        self.build_toolbar()

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)

        splitter = QSplitter(Qt.Horizontal)
        root_layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        self.form_layout = QVBoxLayout(scroll_content)
        self.form_layout.setContentsMargins(10, 10, 10, 10)
        self.form_layout.setSpacing(12)
        scroll.setWidget(scroll_content)
        left_layout.addWidget(scroll)

        self.build_form()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        preview_top = QHBoxLayout()
        self.preview_scale_slider = QSlider(Qt.Horizontal)
        self.preview_scale_slider.setRange(20, 100)
        self.preview_scale_slider.setValue(45)
        self.preview_scale_slider.valueChanged.connect(self.schedule_preview_update)
        self.preview_scale_label = QLabel("プレビュー縮尺: 45%")
        self.preview_scale_slider.valueChanged.connect(
            lambda v: self.preview_scale_label.setText(f"プレビュー縮尺: {v}%")
        )
        preview_top.addWidget(self.preview_scale_label)
        preview_top.addWidget(self.preview_scale_slider)
        right_layout.addLayout(preview_top)

        self.preview_label = PreviewLabel()
        right_layout.addWidget(self.preview_label, 1)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([560, 1040])

    def build_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        act_new = QAction("新規", self)
        act_open = QAction("JSON読込", self)
        act_save_json = QAction("JSON保存", self)
        act_save_json_as = QAction("JSON別名保存", self)
        act_export_png = QAction("PNG出力", self)
        act_font = QAction("フォント選択", self)
        act_reset_layout = QAction("レイアウト初期化", self)
        act_reset_theme = QAction("色初期化", self)

        act_new.triggered.connect(self.load_default_example)
        act_open.triggered.connect(self.open_json)
        act_save_json.triggered.connect(self.save_json)
        act_save_json_as.triggered.connect(self.save_json_as)
        act_export_png.triggered.connect(self.export_png)
        act_font.triggered.connect(self.choose_font)
        act_reset_layout.triggered.connect(self.reset_layout)
        act_reset_theme.triggered.connect(self.reset_theme)

        for act in [act_new, act_open, act_save_json, act_save_json_as, act_export_png, act_font, act_reset_layout, act_reset_theme]:
            toolbar.addAction(act)

    def build_form(self):
        self.form_layout.addWidget(self.make_section_label("基本情報"))

        basic_form = QFormLayout()
        self.title_edit = QLineEdit()
        self.profile_title_edit = QLineEdit()
        self.story_title_edit = QLineEdit()
        basic_form.addRow("タイトル", self.title_edit)
        basic_form.addRow("左見出し", self.profile_title_edit)
        basic_form.addRow("右見出し", self.story_title_edit)
        self.form_layout.addLayout(basic_form)

        self.form_layout.addWidget(self.make_section_label("設定欄"))
        self.profile_text_edit = QTextEdit()
        self.profile_text_edit.setPlaceholderText("1行ごとに設定を書く")
        self.profile_text_edit.setMinimumHeight(180)
        self.form_layout.addWidget(self.profile_text_edit)

        self.form_layout.addWidget(self.make_section_label("ストーリー欄"))
        self.story_text_edit = QTextEdit()
        self.story_text_edit.setMinimumHeight(220)
        self.form_layout.addWidget(self.story_text_edit)

        self.form_layout.addWidget(self.make_section_label("画像"))
        self.main_img_widgets = self.build_image_editor("メイン画像")
        self.sub_img_widgets = self.build_image_editor("サブ画像")

        self.form_layout.addWidget(self.make_section_label("レイアウト"))
        self.layout_widgets = self.build_layout_editors()

        self.form_layout.addWidget(self.make_section_label("色"))
        self.theme_widgets = self.build_theme_editors()

        self.form_layout.addStretch(1)

        self.connect_change_signals()

    def make_section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; font-size: 16px; padding: 6px 0;")
        return lbl

    def build_image_editor(self, title: str) -> dict:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(title_label)

        path_row = QHBoxLayout()
        path_edit = QLineEdit()
        browse_btn = QPushButton("参照")
        clear_btn = QPushButton("クリア")
        path_row.addWidget(path_edit, 1)
        path_row.addWidget(browse_btn)
        path_row.addWidget(clear_btn)
        layout.addLayout(path_row)

        form = QFormLayout()
        zoom_spin = QSpinBox()
        zoom_spin.setRange(10, 400)
        zoom_spin.setSuffix(" %")
        offset_x = QSpinBox()
        offset_y = QSpinBox()
        for sb in (offset_x, offset_y):
            sb.setRange(-5000, 5000)
        form.addRow("ズーム", zoom_spin)
        form.addRow("Xオフセット", offset_x)
        form.addRow("Yオフセット", offset_y)
        layout.addLayout(form)

        self.form_layout.addWidget(frame)

        return {
            "frame": frame,
            "path_edit": path_edit,
            "browse_btn": browse_btn,
            "clear_btn": clear_btn,
            "zoom_spin": zoom_spin,
            "offset_x": offset_x,
            "offset_y": offset_y,
            "title": title,
        }

    def build_layout_editors(self) -> dict:
        form = QFormLayout()

        def make_spin(min_v: int, max_v: int):
            sb = QSpinBox()
            sb.setRange(min_v, max_v)
            return sb

        widgets = {
            "width": make_spin(400, 8000),
            "height": make_spin(300, 8000),
            "margin": make_spin(0, 300),
            "gap": make_spin(0, 300),
            "left_top_h": make_spin(20, 1200),
            "left_mid_h": make_spin(20, 1200),
            "right_top_h": make_spin(20, 1200),
            "right_bottom_h": make_spin(20, 1200),
        }

        for key, label in [
            ("width", "幅"),
            ("height", "高さ"),
            ("margin", "外側余白"),
            ("gap", "列間ギャップ"),
            ("left_top_h", "左上パネル高"),
            ("left_mid_h", "左中パネル高"),
            ("right_top_h", "右上パネル高"),
            ("right_bottom_h", "右下画像高"),
        ]:
            form.addRow(label, widgets[key])

        self.keep_ratio_check = QCheckBox("左右列比率は固定（0.32 / 0.32 / 残り）")
        self.keep_ratio_check.setChecked(True)

        self.form_layout.addLayout(form)
        self.form_layout.addWidget(self.keep_ratio_check)
        return widgets

    def build_theme_editors(self) -> dict:
        widgets = {
            "canvas_bg": ColorButton("キャンバス背景", (210, 210, 210)),
            "panel_bg": ColorButton("パネル背景", (181, 237, 226)),
            "border": ColorButton("枠線", (0, 0, 0)),
            "text": ColorButton("文字色", (0, 0, 0)),
        }
        form = QFormLayout()
        form.addRow("キャンバス背景", widgets["canvas_bg"])
        form.addRow("パネル背景", widgets["panel_bg"])
        form.addRow("枠線", widgets["border"])
        form.addRow("文字色", widgets["text"])

        self.border_width_spin = QSpinBox()
        self.border_width_spin.setRange(1, 30)
        self.padding_spin = QSpinBox()
        self.padding_spin.setRange(0, 100)
        form.addRow("枠線太さ", self.border_width_spin)
        form.addRow("内側余白", self.padding_spin)

        self.form_layout.addLayout(form)
        return widgets

    def connect_change_signals(self):
        self.title_edit.textChanged.connect(self.on_form_changed)
        self.profile_title_edit.textChanged.connect(self.on_form_changed)
        self.story_title_edit.textChanged.connect(self.on_form_changed)
        self.profile_text_edit.textChanged.connect(self.on_form_changed)
        self.story_text_edit.textChanged.connect(self.on_form_changed)

        for widgets in [self.main_img_widgets, self.sub_img_widgets]:
            widgets["path_edit"].textChanged.connect(self.on_form_changed)
            widgets["zoom_spin"].valueChanged.connect(self.on_form_changed)
            widgets["offset_x"].valueChanged.connect(self.on_form_changed)
            widgets["offset_y"].valueChanged.connect(self.on_form_changed)

        self.main_img_widgets["browse_btn"].clicked.connect(lambda: self.pick_image(self.main_img_widgets))
        self.sub_img_widgets["browse_btn"].clicked.connect(lambda: self.pick_image(self.sub_img_widgets))
        self.main_img_widgets["clear_btn"].clicked.connect(lambda: self.clear_image(self.main_img_widgets))
        self.sub_img_widgets["clear_btn"].clicked.connect(lambda: self.clear_image(self.sub_img_widgets))

        for sb in self.layout_widgets.values():
            sb.valueChanged.connect(self.on_form_changed)

        self.border_width_spin.valueChanged.connect(self.on_form_changed)
        self.padding_spin.valueChanged.connect(self.on_form_changed)

    # ------------------------------
    # State/UI Sync
    # ------------------------------
    def on_form_changed(self):
        if self._updating_ui:
            return
        self.update_state_from_ui()
        self.schedule_preview_update()

    def update_state_from_ui(self):
        self.state.data.title = self.title_edit.text().strip() or "キャラクター名"
        self.state.data.profile_title = self.profile_title_edit.text().strip() or "設定"
        self.state.data.story_title = self.story_title_edit.text().strip() or "ストーリー"

        profile_lines = [line.rstrip() for line in self.profile_text_edit.toPlainText().splitlines()]
        self.state.data.profile_lines = [line for line in profile_lines if line != ""] or [""]
        self.state.data.story_text = self.story_text_edit.toPlainText().rstrip()

        self.state.data.main_image.path = self.main_img_widgets["path_edit"].text().strip() or None
        self.state.data.main_image.zoom_percent = self.main_img_widgets["zoom_spin"].value()
        self.state.data.main_image.offset_x = self.main_img_widgets["offset_x"].value()
        self.state.data.main_image.offset_y = self.main_img_widgets["offset_y"].value()

        self.state.data.sub_image.path = self.sub_img_widgets["path_edit"].text().strip() or None
        self.state.data.sub_image.zoom_percent = self.sub_img_widgets["zoom_spin"].value()
        self.state.data.sub_image.offset_x = self.sub_img_widgets["offset_x"].value()
        self.state.data.sub_image.offset_y = self.sub_img_widgets["offset_y"].value()

        self.state.layout.width = self.layout_widgets["width"].value()
        self.state.layout.height = self.layout_widgets["height"].value()
        self.state.layout.margin = self.layout_widgets["margin"].value()
        self.state.layout.gap = self.layout_widgets["gap"].value()
        self.state.layout.left_top_h = self.layout_widgets["left_top_h"].value()
        self.state.layout.left_mid_h = self.layout_widgets["left_mid_h"].value()
        self.state.layout.right_top_h = self.layout_widgets["right_top_h"].value()
        self.state.layout.right_bottom_h = self.layout_widgets["right_bottom_h"].value()

        self.state.theme.canvas_bg = self.theme_widgets["canvas_bg"].rgb
        self.state.theme.panel_bg = self.theme_widgets["panel_bg"].rgb
        self.state.theme.border = self.theme_widgets["border"].rgb
        self.state.theme.text = self.theme_widgets["text"].rgb
        self.state.theme.border_width = self.border_width_spin.value()
        self.state.theme.padding = self.padding_spin.value()

    def refresh_ui_from_state(self):
        self._updating_ui = True
        try:
            self.title_edit.setText(self.state.data.title)
            self.profile_title_edit.setText(self.state.data.profile_title)
            self.story_title_edit.setText(self.state.data.story_title)
            self.profile_text_edit.setPlainText("\n".join(self.state.data.profile_lines))
            self.story_text_edit.setPlainText(self.state.data.story_text)

            self.set_image_editor_values(self.main_img_widgets, self.state.data.main_image)
            self.set_image_editor_values(self.sub_img_widgets, self.state.data.sub_image)

            self.layout_widgets["width"].setValue(self.state.layout.width)
            self.layout_widgets["height"].setValue(self.state.layout.height)
            self.layout_widgets["margin"].setValue(self.state.layout.margin)
            self.layout_widgets["gap"].setValue(self.state.layout.gap)
            self.layout_widgets["left_top_h"].setValue(self.state.layout.left_top_h)
            self.layout_widgets["left_mid_h"].setValue(self.state.layout.left_mid_h)
            self.layout_widgets["right_top_h"].setValue(self.state.layout.right_top_h)
            self.layout_widgets["right_bottom_h"].setValue(self.state.layout.right_bottom_h)

            self.theme_widgets["canvas_bg"].set_rgb(self.state.theme.canvas_bg)
            self.theme_widgets["panel_bg"].set_rgb(self.state.theme.panel_bg)
            self.theme_widgets["border"].set_rgb(self.state.theme.border)
            self.theme_widgets["text"].set_rgb(self.state.theme.text)
            self.border_width_spin.setValue(self.state.theme.border_width)
            self.padding_spin.setValue(self.state.theme.padding)
        finally:
            self._updating_ui = False

    def set_image_editor_values(self, widgets: dict, placement: ImagePlacement):
        widgets["path_edit"].setText(placement.path or "")
        widgets["zoom_spin"].setValue(placement.zoom_percent)
        widgets["offset_x"].setValue(placement.offset_x)
        widgets["offset_y"].setValue(placement.offset_y)

    # ------------------------------
    # Actions
    # ------------------------------
    def load_default_example(self):
        self.current_json_path = None
        self.state = state_from_json_dict(DEFAULT_JSON_EXAMPLE)
        self.refresh_ui_from_state()
        self.schedule_preview_update()

    def open_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "JSON読込", "", "JSON Files (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.state = state_from_json_dict(raw)
            self.current_json_path = path
            self.refresh_ui_from_state()
            self.schedule_preview_update()
        except Exception as e:
            QMessageBox.critical(self, "読込エラー", f"JSONの読込に失敗しました。\n\n{e}")

    def save_json(self):
        self.update_state_from_ui()
        if not self.current_json_path:
            return self.save_json_as()
        try:
            with open(self.current_json_path, "w", encoding="utf-8") as f:
                json.dump(state_to_json_dict(self.state), f, ensure_ascii=False, indent=2)
            QMessageBox.information(self, "保存完了", f"保存しました。\n{self.current_json_path}")
        except Exception as e:
            QMessageBox.critical(self, "保存エラー", f"JSON保存に失敗しました。\n\n{e}")

    def save_json_as(self):
        self.update_state_from_ui()
        path, _ = QFileDialog.getSaveFileName(self, "JSON別名保存", "character_sheet.json", "JSON Files (*.json)")
        if not path:
            return
        self.current_json_path = path
        self.save_json()

    def export_png(self):
        self.update_state_from_ui()
        path, _ = QFileDialog.getSaveFileName(self, "PNG出力", "character_sheet.png", "PNG Files (*.png)")
        if not path:
            return
        try:
            result = save_character_sheet(self.state, path)
            QMessageBox.information(self, "出力完了", f"PNGを書き出しました。\n{result}")
        except Exception as e:
            QMessageBox.critical(self, "出力エラー", f"PNG出力に失敗しました。\n\n{e}")

    def choose_font(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "フォント選択",
            "",
            "Font Files (*.ttf *.ttc *.otf);;All Files (*)",
        )
        if not path:
            return
        self.state.font_path = path
        self.schedule_preview_update()

    def reset_layout(self):
        self.state.layout = Layout()
        self.refresh_ui_from_state()
        self.schedule_preview_update()

    def reset_theme(self):
        self.state.theme = Theme()
        self.refresh_ui_from_state()
        self.schedule_preview_update()

    def pick_image(self, widgets: dict):
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"{widgets['title']}を選択",
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        widgets["path_edit"].setText(path)

    def clear_image(self, widgets: dict):
        widgets["path_edit"].clear()
        widgets["zoom_spin"].setValue(100)
        widgets["offset_x"].setValue(0)
        widgets["offset_y"].setValue(0)

    # ------------------------------
    # Preview
    # ------------------------------
    def schedule_preview_update(self):
        self.update_state_from_ui()
        self._preview_timer.start(120)

    def refresh_preview(self):
        try:
            scale = self.preview_scale_slider.value() / 100.0
            image = generate_character_sheet_image(self.state, preview_scale=scale)
            qt_image = self.pil_to_qimage(image)
            pixmap = QPixmap.fromImage(qt_image)
            self.preview_label.set_preview_pixmap(pixmap)
        except Exception as e:
            logger.exception("Failed to refresh preview")
            self.preview_label.setText(f"プレビュー生成失敗\n{e}")

    @staticmethod
    def pil_to_qimage(image: Image.Image) -> QImage:
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        qimage = ImageQt.ImageQt(image)
        return qimage.copy()


def main():
    logging.basicConfig(level=logging.INFO)
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
