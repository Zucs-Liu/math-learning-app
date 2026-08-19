"""Boss battle animation timeline and Streamlit presentation."""

import base64
import re
from pathlib import Path

import streamlit as st

from game_data.config import BOSS_CONFIGS
from game_ui.common import force_top_before_navigation


APP_ROOT = Path(__file__).resolve().parent.parent
SKILL_CINEMATIC_SECONDS = 1.5
SKILL_DRAGON_FLIGHT_SECONDS = 2.0
SKILL_IMPACT_SECONDS = 1.0


def battle_presentation_state(result, real_elapsed):
    """把技能演出插入戰鬥時間軸；演出期間模擬時間暫停。"""
    skill_events = [event for event in result["events"] if "施放技能" in event["text"]]
    paused_seconds = 0.0
    active_skill = None
    simulated_elapsed = real_elapsed
    for event in skill_events:
        cinematic_start = event["time"] + paused_seconds
        if real_elapsed < cinematic_start:
            break
        if real_elapsed < cinematic_start + SKILL_CINEMATIC_SECONDS:
            active_skill = {**event, "presentation_phase": "announcement"}
            simulated_elapsed = max(0.0, event["time"] - 0.001)
            break
        flight_start = cinematic_start + SKILL_CINEMATIC_SECONDS
        if real_elapsed < flight_start + SKILL_DRAGON_FLIGHT_SECONDS:
            active_skill = {**event, "presentation_phase": "dragon_flight"}
            simulated_elapsed = max(0.0, event["time"] - 0.001)
            break
        impact_start = flight_start + SKILL_DRAGON_FLIGHT_SECONDS
        if real_elapsed < impact_start + SKILL_IMPACT_SECONDS:
            active_skill = {**event, "presentation_phase": "aftermath"}
            simulated_elapsed = event["time"]
            break
        paused_seconds += (
            SKILL_CINEMATIC_SECONDS + SKILL_DRAGON_FLIGHT_SECONDS + SKILL_IMPACT_SECONDS
        )
        simulated_elapsed = real_elapsed - paused_seconds
    presentation_duration = result["duration"] + len(skill_events) * (
        SKILL_CINEMATIC_SECONDS + SKILL_DRAGON_FLIGHT_SECONDS + SKILL_IMPACT_SECONDS
    )
    return simulated_elapsed, active_skill, presentation_duration


@st.cache_data(show_spinner=False)
def boss_image_data_uri(filename):
    image_path = APP_ROOT / "assets" / "bosses" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


@st.cache_data(show_spinner=False)
def effect_image_data_uri(filename):
    image_path = APP_ROOT / "assets" / "effects" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


@st.cache_data(show_spinner=False)
def hero_image_data_uri(gender="male"):
    filename = "blue-silver-hero-female.webp" if gender == "female" else "blue-silver-hero.webp"
    image_path = APP_ROOT / "assets" / "heroes" / filename
    if not image_path.exists():
        return ""
    return "data:image/webp;base64," + base64.b64encode(image_path.read_bytes()).decode("ascii")


def render_battle_scene(event, chapter_id, boss_type, event_sequence, active_skill=None, gender="male"):
    skill_phase = active_skill.get("presentation_phase") if active_skill else None
    skill_flight = skill_phase == "dragon_flight"
    skill_impact = skill_phase == "aftermath"
    active_skill_text = active_skill.get("text", "") if active_skill else ""
    is_lightning_skill = "天降雷劫" in active_skill_text
    is_wind_skill = "狂風驟雨" in active_skill_text
    hero_attacking = event["text"].startswith("勇者") and active_skill is None
    boss_attacking = ("BOSS第" in event["text"] or "BOSS發動" in event["text"]) and active_skill is None
    critical_hit = "暴擊" in event["text"]
    hero_defeated = event.get("player_hp", 1) <= 0
    boss_defeated = event.get("boss_hp", 1) <= 0
    hero_class = "fighter hero hero-attack" if hero_attacking else "fighter hero"
    boss_class = "fighter boss boss-attack" if boss_attacking else "fighter boss"
    # 模擬器在0秒同時建立「戰鬥開始」與勇者第一擊，因此前兩筆才是入場畫面。
    if event_sequence <= 2:
        hero_class += " enter-battle hero-enter"
        boss_class += " enter-battle boss-enter"
    if hero_defeated:
        hero_class += " defeated"
    if boss_defeated:
        boss_class += " defeated"
    hero_hit = boss_attacking or (skill_impact and not is_wind_skill)
    boss_hit = hero_attacking
    if hero_hit and not hero_defeated:
        hero_class += " hit-shake"
    if boss_hit and not boss_defeated:
        boss_class += " hit-shake"
    hero_claws = '<div class="claw-hit hero-claw"><i></i><i></i><i></i></div>' if hero_hit else ""
    boss_claws = '<div class="claw-hit boss-claw"><i></i><i></i><i></i></div>' if boss_hit else ""
    sword_slash = '<div class="sword-slash"></div>' if hero_attacking else ""
    damage_match = re.search(r"造成\s*([0-9.]+)", event["text"])
    damage_text = damage_match.group(1) if damage_match else ""
    damage_overlay = ""
    if damage_text and active_skill is None:
        target_class = "damage-on-boss" if hero_attacking else "damage-on-hero"
        critical_class = " critical-number" if critical_hit else ""
        prefix = "暴擊 " if critical_hit else "-"
        damage_overlay = f'<div class="damage-number {target_class}{critical_class}">{prefix}{damage_text}</div>'
    boss_config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    boss_image = boss_image_data_uri(boss_config["image"])
    hero_image = hero_image_data_uri(gender)
    hero_visual = (
        f'<img class="hero-portrait" src="{hero_image}" alt="勇者">'
        if hero_image else '<div class="hero-fallback">🦸</div>'
    )
    boss_visual = (
        f'<img class="boss-portrait" src="{boss_image}" alt="{boss_config["name"]}">'
        if boss_image else '<div class="boss-fallback">🐉</div>'
    )
    skill_overlay = ""
    if skill_phase == "announcement":
        cinematic_class = (
            "lightning-cinematic" if is_lightning_skill
            else "wind-cinematic" if is_wind_skill else ""
        )
        skill_icon = "⚡" if is_lightning_skill else "🌪️" if is_wind_skill else "🔥"
        skill_overlay = (
            f'<div class="skill-cinematic {cinematic_class}"><div class="skill-flame">{skill_icon}</div>'
            f'<strong>{active_skill["text"]}</strong><div>戰鬥計時暫停</div></div>'
        )
    elif skill_impact:
        if is_wind_skill:
            impact_text = "勇者造成傷害 -40%"
        else:
            skill_damage = re.search(r"造成\s*([0-9.]+)", active_skill["text"])
            skill_damage_text = skill_damage.group(1) if skill_damage else ""
            impact_text = (
                f"{'雷劫傷害' if is_lightning_skill else '真實傷害'} -{skill_damage_text}"
            )
        skill_overlay = (
            '<div class="skill-aftermath-layer">'
            f'<div class="true-damage-number">{impact_text}</div>'
            '</div>'
        )
    elif skill_flight:
        if is_lightning_skill:
            skill_overlay = (
                '<div class="dragon-skill-layer lightning-skill-layer">'
                '<div class="storm-cloud cloud-left"></div>'
                '<div class="storm-cloud cloud-right"></div>'
                '<svg class="lightning-svg" viewBox="0 0 1000 1000" preserveAspectRatio="none">'
                '<defs><filter id="lightning-glow"><feGaussianBlur stdDeviation="8" result="blur"/>'
                '<feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>'
                '<path class="lightning-path main-lightning" pathLength="1" d="M535,-30 L470,155 L545,230 L420,390 L505,470 L350,650 L455,705 L315,1010"/>'
                '<path class="lightning-path lightning-branch branch-one" pathLength="1" d="M474,156 L335,260 L245,390"/>'
                '<path class="lightning-path lightning-branch branch-two" pathLength="1" d="M424,390 L620,455 L710,590"/>'
                '<path class="lightning-path lightning-branch branch-three" pathLength="1" d="M353,650 L190,720 L105,870"/>'
                '<path class="lightning-path lightning-branch branch-four" pathLength="1" d="M456,705 L650,760 L785,930"/>'
                '</svg>'
                '<div class="lightning-screen-flash"></div>'
                '<div class="lightning-impact-glow"></div></div>'
            )
        elif is_wind_skill:
            skill_overlay = (
                '<div class="dragon-skill-layer wind-skill-layer">'
                '<div class="wind-cloud wind-cloud-one"></div>'
                '<div class="wind-cloud wind-cloud-two"></div>'
                '<div class="wind-rain-curtain"></div>'
                '<div class="wind-streak streak-one"></div>'
                '<div class="wind-streak streak-two"></div>'
                '<div class="wind-streak streak-three"></div>'
                '<div class="tornado-stage">'
                '<div class="tornado-backwash"></div>'
                '<svg class="tornado-svg" viewBox="0 0 700 1000" preserveAspectRatio="xMidYMid meet">'
                '<defs>'
                '<linearGradient id="windBodyGradient" x1="0" y1="0" x2="1" y2="1">'
                '<stop offset="0" stop-color="#dff9ff" stop-opacity=".88"/>'
                '<stop offset=".28" stop-color="#7899a5" stop-opacity=".75"/>'
                '<stop offset=".60" stop-color="#263c47" stop-opacity=".9"/>'
                '<stop offset="1" stop-color="#bdebf2" stop-opacity=".68"/>'
                '</linearGradient>'
                '<filter id="windRough" x="-30%" y="-20%" width="160%" height="150%">'
                '<feTurbulence type="fractalNoise" baseFrequency=".012 .035" numOctaves="3" seed="8" result="noise">'
                '<animate attributeName="baseFrequency" dur=".65s" values=".012 .035;.020 .055;.012 .035" repeatCount="indefinite"/>'
                '</feTurbulence>'
                '<feDisplacementMap in="SourceGraphic" in2="noise" scale="34" xChannelSelector="R" yChannelSelector="B"/>'
                '</filter>'
                '</defs>'
                '<path class="tornado-body" filter="url(#windRough)" fill="url(#windBodyGradient)" '
                'd="M60 82 C155 14 545 14 640 82 C620 170 565 225 550 325 '
                'C530 440 475 500 454 610 C435 720 400 810 371 938 '
                'C363 976 337 976 329 938 C300 810 265 720 246 610 '
                'C225 500 170 440 150 325 C135 225 80 170 60 82 Z"/>'
                '<g class="tornado-ribbons">'
                '<path d="M72 112 C210 38 525 40 628 125 C518 205 205 215 100 151"/>'
                '<path d="M122 245 C240 181 495 188 566 263 C474 330 225 338 155 285"/>'
                '<path d="M158 378 C252 325 459 330 520 398 C432 460 250 462 190 419"/>'
                '<path d="M207 515 C280 471 425 477 470 535 C399 585 284 590 231 552"/>'
                '<path d="M245 646 C302 612 397 615 431 663 C381 704 300 709 263 680"/>'
                '<path d="M282 770 C318 745 379 748 402 785 C369 817 315 821 294 798"/>'
                '<path d="M314 884 C335 868 371 871 383 897 C362 918 332 920 320 905"/>'
                '</g></svg>'
                '<div class="tornado-ground-shadow"></div>'
                '<div class="tornado-dust dust-far"></div>'
                '<div class="tornado-dust dust-near"></div>'
                '<div class="wind-debris debris-one">◆</div>'
                '<div class="wind-debris debris-two">●</div>'
                '<div class="wind-debris debris-three">▲</div>'
                '<div class="wind-debris debris-four">▰</div>'
                '<div class="wind-debris debris-five">◆</div>'
                '</div><div class="wind-vignette"></div>'
                '</div>'
            )
        else:
            fire_dragon_image = effect_image_data_uri("fire-dragon-strike.webp")
            dragon_visual = (
                f'<img class="eastern-fire-dragon" src="{fire_dragon_image}" alt="火龍斬">'
                if fire_dragon_image else '<div class="fire-dragon-fallback">🐉</div>'
            )
            skill_overlay = f'<div class="dragon-skill-layer">{dragon_visual}</div>'
    if skill_flight:
        arena_class = "battle-arena skill-flight-arena"
    elif skill_impact and not is_wind_skill:
        arena_class = "battle-arena skill-impact-arena"
    else:
        arena_class = "battle-arena"
    st.markdown(
        f"""
        <style>
        .battle-arena {{position:relative;height:270px;margin:14px 0 18px;padding:24px;
          overflow:hidden;border-radius:22px;background:radial-gradient(circle at 50% 20%,#fff9 0 8%,transparent 36%),linear-gradient(#ccecff 0 60%,#8fc96f 60% 66%,#628f48 66%);
          border:2px solid #d8e1ea;display:flex;align-items:flex-end;justify-content:space-between;perspective:900px;isolation:isolate;}}
        .battle-arena:after {{content:"";position:absolute;left:7%;right:7%;bottom:22px;height:34px;background:#18320d33;border-radius:50%;filter:blur(8px);z-index:-1;}}
        .fighter {{position:relative;font-size:88px;line-height:1;text-align:center;transform-style:preserve-3d;filter:drop-shadow(0 12px 7px #0005);animation:idleFloat 1.35s ease-in-out infinite alternate;will-change:transform;}}
        .boss-portrait,.hero-portrait {{width:168px;height:168px;object-fit:cover;border:0;border-radius:0;
          mix-blend-mode:multiply;-webkit-mask-image:radial-gradient(ellipse 52% 58% at 50% 48%,#000 58%,#000d 72%,transparent 100%);
          mask-image:radial-gradient(ellipse 52% 58% at 50% 48%,#000 58%,#000d 72%,transparent 100%);}}
        .boss-fallback {{font-size:100px;line-height:150px;}}
        .hero-fallback {{font-size:100px;line-height:150px;}}
        .fighter span {{display:block;margin-top:10px;font-size:20px;font-weight:700;color:#313442;}}
        .hero-attack {{z-index:3;animation:heroStrike{event_sequence} .62s cubic-bezier(.2,.8,.2,1);}}
        .boss-attack {{z-index:3;animation:bossStrike{event_sequence} .62s cubic-bezier(.2,.8,.2,1);}}
        .hero-attack .hero-portrait,.boss-attack .boss-portrait {{filter:brightness(1.12) saturate(1.18);}}
        .hit-shake .hero-portrait,.hit-shake .boss-portrait {{animation:hitShake{event_sequence} .52s ease-out;}}
        .sword-slash {{position:absolute;z-index:6;right:-105px;top:18px;width:125px;height:125px;border-radius:50%;border-right:12px solid #fff;border-top:7px solid #6de7ff;filter:drop-shadow(0 0 8px #2ecbff);transform:rotate(28deg);animation:swordArc{event_sequence} .55s ease-out forwards;}}
        .claw-hit {{position:absolute;z-index:4;inset:8px 12px 34px;pointer-events:none;
          animation:clawFlash{event_sequence} .65s ease-out forwards;}}
        .claw-hit i {{position:absolute;left:48%;top:8%;width:8px;height:82%;border-radius:8px;
          background:linear-gradient(90deg,#fff,#ff304f 35%,#8b0016);box-shadow:0 0 12px #ff173c;
          transform:rotate(32deg);}}
        .claw-hit i:nth-child(1) {{margin-left:-30px;}}
        .claw-hit i:nth-child(2) {{margin-left:0;}}
        .claw-hit i:nth-child(3) {{margin-left:30px;}}
        .skill-cinematic {{position:absolute;inset:0;z-index:5;display:flex;flex-direction:column;
          align-items:center;justify-content:center;color:white;font-size:26px;text-align:center;
          background:radial-gradient(circle,#ff7a18dd,#8b0000ee);animation:skillFlash .55s ease-in-out infinite alternate;}}
        .skill-flame {{font-size:82px;animation:flameGrow .5s ease-in-out infinite alternate;}}
        .lightning-cinematic {{background:radial-gradient(circle,#8a5cffdd,#17002fee);}}
        .wind-cinematic {{background:radial-gradient(circle at 50% 45%,#55758ddd,#07131fee 72%);}}
        .skill-flight-arena {{background:#000;border-color:#000;box-shadow:none;overflow:visible;perspective:none;}}
        .skill-flight-arena:after {{display:none;}}
        .skill-flight-arena > .fighter {{visibility:hidden;}}
        .dragon-skill-layer {{position:fixed;inset:0;z-index:999999;pointer-events:none;overflow:hidden;background:#000;}}
        .eastern-fire-dragon {{position:absolute;left:100%;top:-42%;width:min(760px,92vw);height:auto;
          max-width:none;filter:drop-shadow(0 0 14px #ff2400) drop-shadow(0 0 36px #ff8500);
          transform-origin:center;animation:dragonRush{event_sequence} 2s linear forwards;will-change:transform,opacity;}}
        .fire-dragon-fallback {{position:absolute;left:100%;top:-20%;font-size:150px;
          animation:dragonRush{event_sequence} 2s linear forwards;}}
        .lightning-skill-layer {{background:#000;}}
        .lightning-svg {{position:absolute;inset:-2% 0 0;width:100%;height:104%;overflow:visible;
          filter:drop-shadow(0 0 7px #fff) drop-shadow(0 0 22px #8a46ff);}}
        .lightning-path {{fill:none;stroke:#f8f3ff;stroke-linecap:round;stroke-linejoin:round;
          filter:url(#lightning-glow);stroke-dasharray:1;stroke-dashoffset:1;
          animation:lightningTrace{event_sequence} 2s cubic-bezier(.12,.72,.25,1) forwards;}}
        .main-lightning {{stroke-width:18;}}
        .lightning-branch {{stroke:#cdafff;stroke-width:8;}}
        .branch-one {{animation-delay:.18s;}} .branch-two {{animation-delay:.32s;}}
        .branch-three {{animation-delay:.46s;}} .branch-four {{animation-delay:.58s;}}
        .storm-cloud {{position:absolute;top:-8%;width:62%;height:30%;border-radius:50%;
          background:radial-gradient(ellipse at center,#695088 0 18%,#291b45 48%,transparent 72%);
          filter:blur(16px);opacity:0;animation:stormCloudIn{event_sequence} 2s ease-out forwards;}}
        .cloud-left {{left:-8%;}} .cloud-right {{right:-8%;animation-delay:.12s;}}
        .lightning-screen-flash {{position:absolute;inset:0;background:#e8dcff;opacity:0;
          animation:lightningScreenFlash{event_sequence} 2s steps(1,end) forwards;}}
        .lightning-bolt {{position:absolute;top:-15%;left:50%;width:18px;height:125%;
          background:linear-gradient(90deg,#6f2cff,#fff 42%,#d7b8ff 62%,#7028ff);
          box-shadow:0 0 18px #9d55ff,0 0 50px #6e20ff,0 0 90px #b279ff;
          clip-path:polygon(38% 0,100% 0,62% 28%,95% 28%,38% 60%,70% 60%,0 100%,28% 65%,0 65%,42% 34%,10% 34%);
          transform-origin:top center;opacity:0;animation:lightningDrop{event_sequence} 2s ease-in forwards;}}
        .side-bolt {{width:9px;filter:blur(.3px);opacity:0;}}
        .left-bolt {{left:37%;transform:rotate(-8deg);animation-delay:.12s;}}
        .right-bolt {{left:63%;transform:rotate(9deg);animation-delay:.22s;}}
        .lightning-impact-glow {{position:absolute;left:50%;bottom:-12%;width:42vw;height:25vh;
          transform:translateX(-50%);border-radius:50%;background:radial-gradient(ellipse,#fff 0 5%,#a55cffaa 22%,transparent 70%);
          opacity:0;animation:lightningGlow{event_sequence} 2s ease-out forwards;}}
        .wind-skill-layer {{background:radial-gradient(circle at 50% 42%,#274957 0,#0d1b24 45%,#020508 88%);}}
        .wind-cloud {{position:absolute;width:75vw;height:35vh;border-radius:50%;filter:blur(24px);
          background:radial-gradient(ellipse,#b4cbd0aa 0 12%,#47657299 35%,transparent 72%);
          opacity:0;animation:windCloudSweep{event_sequence} 2s ease-in-out forwards;}}
        .wind-cloud-one {{left:-55vw;top:5vh;}} .wind-cloud-two {{right:-55vw;bottom:4vh;animation-delay:.16s;}}
        .wind-rain-curtain {{position:absolute;inset:-30% -20%;opacity:0;
          background:repeating-linear-gradient(111deg,transparent 0 24px,#c8f7ff99 25px 27px,transparent 29px 52px);
          filter:blur(.5px);animation:windRain{event_sequence} .32s linear infinite,
          windRainIn{event_sequence} 2s ease-in-out forwards;}}
        .wind-streak {{position:absolute;left:-35%;width:52%;height:8px;border-radius:50%;
          background:linear-gradient(90deg,transparent,#d9fbff,#7cdcec88,transparent);
          box-shadow:0 0 15px #bff8ff;transform:skewX(-28deg);opacity:0;
          animation:windStreakRush{event_sequence} .62s linear infinite;}}
        .streak-one {{top:25%;}} .streak-two {{top:52%;animation-delay:.18s;}}
        .streak-three {{top:76%;animation-delay:.36s;}}
        .tornado-stage {{position:absolute;left:50%;top:1vh;width:min(72vw,650px);height:98vh;
          transform:translateX(-50%);transform-origin:50% 88%;opacity:0;
          animation:tornadoStageIn{event_sequence} 2s ease-in-out forwards;}}
        .tornado-backwash {{position:absolute;left:50%;top:1%;width:105%;height:30%;transform:translateX(-50%);
          border-radius:50%;background:repeating-radial-gradient(ellipse at center,transparent 0 8%,#bfeaf277 10% 12%,transparent 15% 20%);
          filter:blur(5px);animation:backwashSpin{event_sequence} .7s linear infinite;}}
        .tornado-svg {{position:absolute;inset:0;width:100%;height:100%;overflow:visible;
          filter:drop-shadow(0 0 12px #c9f8ff) drop-shadow(0 0 36px #4a8798);}}
        .tornado-body {{opacity:.88;transform-origin:center;animation:tornadoBodyPulse{event_sequence} .42s ease-in-out infinite alternate;}}
        .tornado-ribbons path {{fill:none;stroke:#e8fdff;stroke-linecap:round;stroke-width:24;
          stroke-dasharray:115 42;filter:drop-shadow(0 0 7px #a9efff);opacity:.92;
          transform-box:fill-box;transform-origin:center;animation:tornadoRibbon{event_sequence} .42s linear infinite;}}
        .tornado-ribbons path:nth-child(even) {{stroke:#6fa9b8;stroke-dasharray:76 31;
          animation-direction:reverse;animation-duration:.34s;}}
        .tornado-ribbons path:nth-child(3),.tornado-ribbons path:nth-child(4) {{stroke-width:20;}}
        .tornado-ribbons path:nth-child(5) {{stroke-width:17;}}
        .tornado-ribbons path:nth-child(6) {{stroke-width:14;}}
        .tornado-ribbons path:nth-child(7) {{stroke-width:11;}}
        .tornado-ground-shadow {{position:absolute;left:50%;bottom:0;width:34%;height:5%;transform:translateX(-50%);
          border-radius:50%;background:#000;box-shadow:0 0 28px 16px #7cd7e066;filter:blur(5px);}}
        .tornado-dust {{position:absolute;left:50%;bottom:-1%;height:12%;border:6px solid #b7d4d6;
          border-left-color:transparent;border-right-color:transparent;border-radius:50%;opacity:0;}}
        .dust-far {{width:56%;animation:dustRing{event_sequence} .62s linear infinite;}}
        .dust-near {{width:82%;animation:dustRing{event_sequence} .62s .22s linear infinite reverse;}}
        .wind-debris {{position:absolute;left:50%;top:48%;color:#d7f7ef;font-size:22px;opacity:0;
          text-shadow:0 0 7px #baf8ff;animation:debrisSpiral{event_sequence} .92s linear infinite;}}
        .debris-one {{--rx:230px;--ry:-210px;}} .debris-two {{--rx:-255px;--ry:-70px;animation-delay:.17s;}}
        .debris-three {{--rx:205px;--ry:155px;animation-delay:.34s;}}
        .debris-four {{--rx:-185px;--ry:245px;animation-delay:.51s;}}
        .debris-five {{--rx:280px;--ry:30px;animation-delay:.68s;}}
        .wind-vignette {{position:absolute;inset:0;background:radial-gradient(circle at 50% 50%,transparent 32%,#000b 100%);
          box-shadow:inset 0 0 100px #000;animation:windVignette{event_sequence} 2s ease-in-out forwards;}}
        .skill-aftermath-layer {{position:absolute;inset:0;z-index:10;pointer-events:none;}}
        .true-damage-number {{position:absolute;left:10%;top:20%;font-size:30px;font-weight:900;color:#fff3a0;
          text-shadow:0 2px 2px #500,0 0 10px #ff2700;opacity:0;animation:trueDamage{event_sequence} 1s ease-out forwards;}}
        .skill-impact-arena {{animation:arenaImpact{event_sequence} 1s ease-in-out;}}
        .damage-number {{position:absolute;z-index:8;top:38px;font-size:28px;font-weight:900;color:#fff;text-shadow:0 2px 2px #000,0 0 8px #e00000;animation:damageRise{event_sequence} .85s ease-out forwards;}}
        .damage-on-hero {{left:18%;}} .damage-on-boss {{right:18%;}}
        .critical-number {{font-size:34px;color:#ffe33b;text-shadow:0 2px 2px #5b1800,0 0 12px #ff8a00;}}
        .defeated {{animation:defeatFall{event_sequence} .9s ease-in forwards !important;transform-origin:bottom center;}}
        .hero-enter {{animation:heroEnter{event_sequence} .72s cubic-bezier(.18,.85,.28,1.15) both;}}
        .boss-enter {{animation:bossEnter{event_sequence} .72s cubic-bezier(.18,.85,.28,1.15) both;}}
        @keyframes idleFloat {{from{{transform:translateY(0) rotateX(1deg);}}to{{transform:translateY(-7px) rotateX(-2deg);}}}}
        @keyframes heroEnter{event_sequence} {{0%{{opacity:0;transform:translateX(-95px) translateY(35px) scale(.42) rotateY(55deg);}}65%{{opacity:1;transform:translateX(18px) translateY(-16px) scale(1.12) rotateY(-8deg);}}100%{{transform:translateX(0) translateY(0) scale(1) rotateY(0);}}}}
        @keyframes bossEnter{event_sequence} {{0%{{opacity:0;transform:translateX(95px) translateY(35px) scale(.42) rotateY(-55deg);}}65%{{opacity:1;transform:translateX(-18px) translateY(-16px) scale(1.12) rotateY(8deg);}}100%{{transform:translateX(0) translateY(0) scale(1) rotateY(0);}}}}
        @keyframes heroStrike{event_sequence} {{0%{{transform:translateX(0) rotate(0) scale(1);}}42%{{transform:translateX(145px) translateY(-12px) rotate(-9deg) scale(1.13);}}62%{{transform:translateX(125px) rotate(5deg) scale(1.08);}}100%{{transform:translateX(0);}}}}
        @keyframes bossStrike{event_sequence} {{0%{{transform:translateX(0) rotate(0) scale(1);}}42%{{transform:translateX(-145px) translateY(-18px) rotate(9deg) scale(1.15);}}62%{{transform:translateX(-120px) rotate(-5deg) scale(1.08);}}100%{{transform:translateX(0);}}}}
        @keyframes swordArc{event_sequence} {{0%{{opacity:0;transform:rotate(-30deg) scale(.35);}}35%{{opacity:1;transform:rotate(35deg) scale(1.2);}}100%{{opacity:0;transform:rotate(95deg) scale(1.45);}}}}
        @keyframes damageRise{event_sequence} {{0%{{opacity:0;transform:translateY(35px) scale(.5);}}25%{{opacity:1;transform:translateY(0) scale(1.2);}}100%{{opacity:0;transform:translateY(-50px) scale(.9);}}}}
        @keyframes hitShake{event_sequence} {{0%,100%{{transform:translateX(0);filter:none;}}18%{{transform:translateX(-11px);filter:sepia(1) saturate(8) hue-rotate(315deg) brightness(1.35);}}38%{{transform:translateX(9px);}}58%{{transform:translateX(-6px);filter:sepia(1) saturate(8) hue-rotate(315deg);}}78%{{transform:translateX(4px);}}}}
        @keyframes defeatFall{event_sequence} {{to{{transform:translateY(35px) rotate(78deg) scale(.82);opacity:.35;filter:grayscale(1);}}}}
        @keyframes clawFlash{event_sequence} {{0%{{opacity:0;transform:scale(1.7);}}25%{{opacity:1;transform:scale(1);}}100%{{opacity:0;transform:scale(.92);}}}}
        @keyframes skillFlash {{to{{filter:brightness(1.35);}}}}
        @keyframes flameGrow {{to{{transform:scale(1.35) rotate(8deg);}}}}
        @keyframes dragonRush{event_sequence} {{0%{{opacity:0;transform:translate(10%,-12%) scale(.58) rotate(-8deg);}}8%{{opacity:1;}}48%{{opacity:1;transform:translate(-105%,58%) scale(1.05) rotate(-8deg);}}88%{{opacity:1;transform:translate(-205%,138%) scale(1.22) rotate(-8deg);}}100%{{opacity:0;transform:translate(-235%,158%) scale(1.3) rotate(-8deg);}}}}
        @keyframes lightningDrop{event_sequence} {{0%{{opacity:0;transform:translateY(-105%) scaleY(.25);}}12%{{opacity:1;}}48%{{opacity:1;transform:translateY(0) scaleY(1);}}62%{{opacity:.35;}}70%{{opacity:1;filter:brightness(1.8);}}100%{{opacity:0;transform:translateY(8%) scaleY(1.04);}}}}
        @keyframes lightningTrace{event_sequence} {{0%{{stroke-dashoffset:1;opacity:0;}}12%{{opacity:1;}}52%{{stroke-dashoffset:0;opacity:1;}}68%{{opacity:.35;}}76%{{opacity:1;stroke-width:24;}}100%{{stroke-dashoffset:0;opacity:0;}}}}
        @keyframes stormCloudIn{event_sequence} {{0%{{opacity:0;transform:translateY(-35%) scale(.7);}}25%{{opacity:.8;}}72%{{opacity:1;transform:translateY(10%) scale(1.25);}}100%{{opacity:0;transform:translateY(18%) scale(1.4);}}}}
        @keyframes lightningScreenFlash{event_sequence} {{0%,43%,55%,72%,100%{{opacity:0;}}45%,57%,74%{{opacity:.52;}}}}
        @keyframes lightningGlow{event_sequence} {{0%,35%{{opacity:0;transform:translateX(-50%) scale(.2);}}52%{{opacity:1;transform:translateX(-50%) scale(1.4);}}100%{{opacity:0;transform:translateX(-50%) scale(2);}}}}
        @keyframes windCloudSweep{event_sequence} {{0%{{opacity:0;transform:translateX(0) scale(.6);}}18%{{opacity:.85;}}70%{{opacity:1;transform:translateX(70vw) scale(1.25);}}100%{{opacity:0;transform:translateX(115vw) scale(1.45);}}}}
        @keyframes windRain{event_sequence} {{from{{transform:translate(0,-5%);}}to{{transform:translate(-80px,14%);}}}}
        @keyframes windRainIn{event_sequence} {{0%,100%{{opacity:0;}}15%,80%{{opacity:.5;}}}}
        @keyframes windStreakRush{event_sequence} {{0%{{left:-45%;opacity:0;}}15%{{opacity:1;}}100%{{left:115%;opacity:0;}}}}
        @keyframes tornadoStageIn{event_sequence} {{0%{{opacity:0;transform:translateX(-50%) scale(.45,.15) rotate(-4deg);}}18%{{opacity:.9;}}55%{{opacity:1;transform:translateX(-50%) scale(1.04,1) rotate(2deg);}}82%{{opacity:1;transform:translateX(-50%) scale(.98,1.03) rotate(-1deg);}}100%{{opacity:0;transform:translateX(-50%) scale(1.16,1.08) rotate(3deg);}}}}
        @keyframes backwashSpin{event_sequence} {{from{{transform:translateX(-50%) rotate(0deg) scaleX(1);}}to{{transform:translateX(-50%) rotate(360deg) scaleX(1.08);}}}}
        @keyframes tornadoBodyPulse{event_sequence} {{from{{transform:skewX(-1.5deg) scaleX(.97);filter:brightness(.9);}}to{{transform:skewX(2deg) scaleX(1.04);filter:brightness(1.2);}}}}
        @keyframes tornadoRibbon{event_sequence} {{from{{stroke-dashoffset:0;transform:translateX(-8px);}}to{{stroke-dashoffset:-157;transform:translateX(8px);}}}}
        @keyframes dustRing{event_sequence} {{0%{{opacity:0;transform:translateX(-50%) scale(.35) rotate(0);}}20%{{opacity:.85;}}100%{{opacity:0;transform:translateX(-50%) scale(1.5) rotate(360deg);}}}}
        @keyframes debrisSpiral{event_sequence} {{0%{{opacity:0;transform:translate(-50%,-50%) rotate(0) translate(12px,0) scale(.35);}}18%{{opacity:1;}}68%{{opacity:1;transform:translate(-50%,-50%) rotate(470deg) translate(var(--rx),var(--ry)) scale(1.15);}}100%{{opacity:0;transform:translate(-50%,-50%) rotate(720deg) translate(var(--rx),var(--ry)) scale(.65);}}}}
        @keyframes windVignette{event_sequence} {{0%,100%{{opacity:0;}}22%,78%{{opacity:1;}}}}
        @keyframes trueDamage{event_sequence} {{0%{{opacity:0;transform:translateY(25px) scale(.5);}}18%{{opacity:1;transform:translateY(0) scale(1.25);}}100%{{opacity:0;transform:translateY(-38px) scale(.95);}}}}
        @keyframes arenaImpact{event_sequence} {{0%,100%{{transform:translate(0,0);filter:none;}}8%{{transform:translate(-12px,6px);filter:brightness(1.5);}}18%{{transform:translate(12px,-6px);}}30%{{transform:translate(-9px,-5px);}}44%{{transform:translate(8px,5px);}}62%{{transform:translate(-5px,0);filter:brightness(1.15);}}}}
        @media (max-width:600px) {{
          .battle-arena {{height:250px;padding:14px;}}
          .eastern-fire-dragon {{width:165vw;left:105%;top:-35%;}}
          .true-damage-number {{left:5%;top:14%;font-size:25px;}}
          .tornado-stage {{width:96vw;height:94vh;top:3vh;}}
          .tornado-ribbons path {{stroke-width:18;}}
        }}
        </style>
        <div class="{arena_class}">
          <div class="{hero_class}">{hero_visual}{hero_claws}{sword_slash}<span>勇者</span></div>
          <div class="{boss_class}">{boss_visual}{boss_claws}<span>{boss_config['name']}</span></div>
          {damage_overlay}
          {skill_overlay}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_chapter_boss_card(chapter_id, boss_type, unlocked):
    """在章節單元下方顯示 BOSS 能力與挑戰入口。"""
    config = BOSS_CONFIGS[f"{chapter_id}_{boss_type}"]
    is_elite = boss_type == "elite"
    label = "菁英 BOSS" if is_elite else "一般 BOSS"
    with st.container(border=True):
        image_col, info_col, button_col = st.columns([0.75, 4, 1.35], vertical_alignment="center")
        image_path = APP_ROOT / "assets" / "bosses" / config["image"]
        if image_path.exists():
            image_col.image(image_path, width=72)
        else:
            image_col.markdown("## 🐉")
        info_col.markdown(f"### {label}｜{config['name']}")
        info_col.write(
            f"**HP：{config['hp']}**　｜　"
            f"**攻擊：每 {config['interval']:g} 秒造成 {config['damage']} 傷害**"
        )
        abilities = []
        if config.get("critical_rate"):
            abilities.append(
                f"暴擊率 {config['critical_rate']:.0%}（每第 5 次攻擊必定暴擊，造成 1.5 倍傷害）"
            )
        if config.get("defense_reduction"):
            abilities.append(
                f"被動：戰鬥期間勇者防禦降低 {config['defense_reduction']}（最低為0；傷害減免仍有效）"
            )
        if config.get("hero_speed_reduction"):
            abilities.append(
                f"被動：戰鬥期間勇者攻擊速度降低 {config['hero_speed_reduction']:.3f} 次／秒（最低保留0.100次／秒）"
            )
        if config.get("hero_damage_reduction"):
            abilities.append(
                f"技能「{config['skill']}」：戰鬥開始立即發動，勇者造成的傷害降低 "
                f"{config['hero_damage_reduction']:.0%}；可與對菁英BOSS傷害加成互相抵銷"
            )
        if config.get("skill"):
            if config.get("skill_at_start"):
                pass
            elif config.get("skill_hp_threshold") is not None:
                threshold_damage = config.get("true_damage", config.get("skill_damage", 0))
                abilities.append(
                    f"技能「{config['skill']}」：血量首次低於 {config['skill_hp_threshold']:.0%} 時，"
                    f"造成 {threshold_damage:g} {'真實傷害（無視防禦與傷害減免）' if config.get('true_damage') is not None else '傷害（可被傷害減免抵銷）'}"
                )
            else:
                abilities.append(
                    f"技能「{config['skill']}」：每 {config['skill_interval']:g} 秒造成 "
                    f"{config['true_damage']:g} 真實傷害"
                )
        info_col.write("**能力／技能：**" + ("；".join(abilities) if abilities else "無"))
        if button_col.button(
            "開始挑戰" if unlocked else "尚未解鎖",
            key=f"chapter_boss_{chapter_id}_{boss_type}",
            disabled=not unlocked,
            type="primary" if unlocked else "secondary",
            use_container_width=True,
        ):
            force_top_before_navigation()
            st.session_state.selected_boss_type = boss_type
            st.session_state.scroll_boss_to_top = True
            st.session_state.screen = "boss_ready"
            st.rerun()
