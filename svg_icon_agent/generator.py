"""Baseline SVG generator agent."""

from __future__ import annotations

import html

from svg_icon_agent.models import IconPlan, SvgArtifact

CANVAS = 256


class SvgGeneratorAgent:
    """Creates deterministic SVG icons from icon plans."""

    def generate(self, plan: IconPlan, stage: str = "baseline") -> SvgArtifact:
        primary, secondary, ink = plan.palette
        elements = [
            f'<rect x="20" y="20" width="216" height="216" rx="40" fill="{secondary}"/>',
            f'<circle cx="202" cy="54" r="17" fill="{primary}" opacity="0.18"/>',
        ]
        elements.extend(_motif_elements(plan, primary, secondary, ink))
        body = "\n  ".join(elements)
        prompt = html.escape(plan.prompt)
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{CANVAS}" height="{CANVAS}" '
            f'data-prompt="{prompt}">\n  {body}\n</svg>\n'
        )
        return SvgArtifact(id=plan.id, stage=stage, svg=svg)


def _motif_elements(plan: IconPlan, primary: str, secondary: str, ink: str) -> list[str]:
    motifs = set(plan.motifs)
    if {"cloud", "download"}.issubset(motifs):
        return _cloud_download(primary, ink)
    if {"shield", "lock"}.issubset(motifs):
        return _shield_lock(primary, ink)
    if {"calendar", "check"}.issubset(motifs):
        return _calendar_check(primary, ink)
    if {"chat", "sparkle"}.issubset(motifs):
        return _chat_spark(primary, ink)
    if "camera" in motifs:
        return _camera(primary, ink)
    if "coffee" in motifs:
        return _coffee(primary, ink)
    if "rocket" in motifs:
        return _rocket(primary, secondary, ink)
    if {"book", "pencil"}.intersection(motifs):
        return _book_pencil(primary, ink)
    if {"mountain", "sun"}.intersection(motifs):
        return _mountain_sun(primary, secondary, ink)
    if {"city", "moon"}.intersection(motifs):
        return _city_night(primary, ink)
    if {"forest", "path"}.intersection(motifs):
        return _forest_path(primary, secondary, ink)
    if {"planet", "flask"}.intersection(motifs):
        return _lab_planet(primary, ink)
    return _generic_symbol(primary, ink)


def _cloud_download(primary: str, ink: str) -> list[str]:
    return [
        f'<path d="M82 143 C60 143 50 129 50 113 C50 96 64 84 82 86 C91 66 111 56 132 61 C149 65 161 79 165 97 C184 96 200 110 200 128 C200 146 186 158 166 158 H82 Z" fill="white" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<line x1="128" y1="100" x2="128" y2="175" stroke="{primary}" stroke-width="14" stroke-linecap="round"/>',
        f'<polyline points="100,146 128,176 156,146" fill="none" stroke="{primary}" stroke-width="14" stroke-linecap="round" stroke-linejoin="round"/>',
    ]


def _shield_lock(primary: str, ink: str) -> list[str]:
    return [
        f'<path d="M128 45 L190 70 V119 C190 158 164 191 128 209 C92 191 66 158 66 119 V70 Z" fill="{primary}" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        '<rect x="101" y="115" width="54" height="48" rx="10" fill="white"/>',
        f'<path d="M112 116 V100 C112 84 144 84 144 100 V116" fill="none" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>',
        f'<circle cx="128" cy="139" r="5" fill="{ink}"/>',
    ]


def _calendar_check(primary: str, ink: str) -> list[str]:
    return [
        f'<rect x="62" y="62" width="132" height="142" rx="18" fill="white" stroke="{ink}" stroke-width="8"/>',
        f'<rect x="62" y="62" width="132" height="38" rx="18" fill="{primary}"/>',
        f'<line x1="91" y1="48" x2="91" y2="77" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>',
        f'<line x1="165" y1="48" x2="165" y2="77" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>',
        f'<polyline points="92,145 119,171 166,123" fill="none" stroke="{primary}" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>',
    ]


def _chat_spark(primary: str, ink: str) -> list[str]:
    return [
        f'<path d="M64 76 H179 C194 76 205 87 205 102 V151 C205 166 194 177 179 177 H116 L77 207 V177 H64 C49 177 38 166 38 151 V102 C38 87 49 76 64 76 Z" fill="white" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<circle cx="88" cy="126" r="7" fill="{primary}"/>',
        f'<circle cx="122" cy="126" r="7" fill="{primary}"/>',
        f'<circle cx="156" cy="126" r="7" fill="{primary}"/>',
        f'<path d="M190 42 L197 59 L214 66 L197 73 L190 90 L183 73 L166 66 L183 59 Z" fill="{primary}"/>',
    ]


def _camera(primary: str, ink: str) -> list[str]:
    return [
        f'<rect x="49" y="79" width="158" height="107" rx="24" fill="{primary}" stroke="{ink}" stroke-width="8"/>',
        '<rect x="78" y="60" width="46" height="25" rx="8" fill="white"/>',
        '<circle cx="128" cy="134" r="34" fill="white"/>',
        f'<circle cx="128" cy="134" r="20" fill="none" stroke="{ink}" stroke-width="8"/>',
        '<circle cx="177" cy="103" r="8" fill="white"/>',
    ]


def _coffee(primary: str, ink: str) -> list[str]:
    return [
        f'<path d="M76 105 H158 V159 C158 183 141 199 117 199 H107 C86 199 76 183 76 159 Z" fill="white" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<path d="M158 121 H178 C191 121 199 130 199 143 C199 157 190 166 176 166 H158" fill="none" stroke="{primary}" stroke-width="10" stroke-linecap="round"/>',
        f'<path d="M94 83 C82 69 105 61 93 47" fill="none" stroke="{primary}" stroke-width="8" stroke-linecap="round"/>',
        f'<path d="M126 83 C114 69 137 61 125 47" fill="none" stroke="{primary}" stroke-width="8" stroke-linecap="round"/>',
        f'<line x1="69" y1="203" x2="166" y2="203" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>',
    ]


def _rocket(primary: str, secondary: str, ink: str) -> list[str]:
    return [
        f'<path d="M130 49 C166 67 187 103 187 145 L146 186 C104 186 68 165 50 129 C81 123 99 105 105 74 C113 65 121 57 130 49 Z" fill="{primary}" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        '<circle cx="143" cy="101" r="18" fill="white"/>',
        f'<path d="M91 165 L69 207 L111 185 Z" fill="{secondary}" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<path d="M158 73 L188 44" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>',
        f'<path d="M70 153 C50 160 39 177 38 201 C63 200 79 189 86 170 Z" fill="#fb923c"/>',
    ]


def _book_pencil(primary: str, ink: str) -> list[str]:
    return [
        f'<path d="M49 75 H111 C123 75 128 84 128 96 V201 C122 193 112 189 99 189 H49 Z" fill="white" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<path d="M207 75 H145 C133 75 128 84 128 96 V201 C134 193 144 189 157 189 H207 Z" fill="white" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<line x1="79" y1="111" x2="107" y2="111" stroke="{primary}" stroke-width="8" stroke-linecap="round"/>',
        f'<line x1="149" y1="111" x2="177" y2="111" stroke="{primary}" stroke-width="8" stroke-linecap="round"/>',
        f'<path d="M165 192 L205 152 L219 166 L179 206 L158 213 Z" fill="{primary}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>',
    ]


def _mountain_sun(primary: str, secondary: str, ink: str) -> list[str]:
    return [
        f'<circle cx="179" cy="82" r="25" fill="{primary}"/>',
        f'<path d="M45 185 L99 103 L136 153 L160 121 L211 185 Z" fill="white" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<path d="M99 103 L118 130 L84 130 Z" fill="{secondary}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>',
        f'<line x1="47" y1="194" x2="209" y2="194" stroke="{primary}" stroke-width="10" stroke-linecap="round"/>',
    ]


def _city_night(primary: str, ink: str) -> list[str]:
    buildings = []
    for x, y, w, h in [(55, 107, 35, 78), (99, 79, 44, 106), (153, 116, 47, 69)]:
        buildings.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="white" stroke="{ink}" stroke-width="7"/>')
    windows = [
        f'<rect x="{x}" y="{y}" width="8" height="8" rx="2" fill="{primary}"/>'
        for x in (70, 114, 132, 170)
        for y in (126, 150)
    ]
    return [
        f'<path d="M182 54 C168 62 164 82 176 96 C188 111 209 108 218 94 C210 99 197 97 188 88 C179 78 177 65 182 54 Z" fill="{primary}"/>',
        *buildings,
        *windows,
        f'<line x1="44" y1="192" x2="212" y2="192" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>',
    ]


def _forest_path(primary: str, secondary: str, ink: str) -> list[str]:
    return [
        f'<polygon points="79,69 42,151 116,151" fill="{primary}" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>',
        f'<polygon points="165,57 119,160 211,160" fill="{primary}" stroke="{ink}" stroke-width="7" stroke-linejoin="round"/>',
        f'<rect x="73" y="151" width="12" height="38" fill="{ink}"/>',
        f'<rect x="159" y="160" width="13" height="36" fill="{ink}"/>',
        f'<path d="M118 202 C119 178 132 160 151 141 C136 163 137 184 151 208 Z" fill="{secondary}" stroke="{ink}" stroke-width="6" stroke-linejoin="round"/>',
        f'<line x1="47" y1="207" x2="210" y2="207" stroke="{primary}" stroke-width="9" stroke-linecap="round"/>',
    ]


def _lab_planet(primary: str, ink: str) -> list[str]:
    return [
        f'<circle cx="156" cy="73" r="28" fill="{primary}" stroke="{ink}" stroke-width="7"/>',
        '<circle cx="146" cy="64" r="5" fill="white"/>',
        '<circle cx="166" cy="81" r="4" fill="white"/>',
        f'<path d="M97 81 H147 L136 123 V184 C136 198 124 207 111 207 H91 C78 207 66 198 66 184 V123 Z" fill="white" stroke="{ink}" stroke-width="8" stroke-linejoin="round"/>',
        f'<path d="M74 159 H129 V184 C129 191 122 198 112 198 H91 C81 198 74 191 74 184 Z" fill="{primary}" opacity="0.75"/>',
        f'<line x1="86" y1="81" x2="158" y2="81" stroke="{ink}" stroke-width="8" stroke-linecap="round"/>',
    ]


def _generic_symbol(primary: str, ink: str) -> list[str]:
    return [
        f'<circle cx="128" cy="128" r="66" fill="white" stroke="{ink}" stroke-width="8"/>',
        f'<path d="M128 73 L144 112 L186 116 L154 143 L164 184 L128 162 L92 184 L102 143 L70 116 L112 112 Z" fill="{primary}"/>',
    ]

