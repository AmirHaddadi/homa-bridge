<div dir="rtl">

# 🎨 هویت بصری HOMA — پرامپت‌های تولید تصویر

این فایل را بده به GPT / DALL·E / Midjourney تا دو دارایی بصری پروژه را بسازد:

| فایل خروجی | کاربرد | نسبت | اندازهٔ پیشنهادی |
|---|---|---|---|
| `assets/logo.png` | لوگو (آواتار مخزن، فاوآیکون) | ۱:۱ مربع | ۱۰۲۴×۱۰۲۴ |
| `assets/banner.png` | بنر افقی بالای README | ~۴:۱ افقی | ۱۵۰۰×۴۰۰ |

## کانسپت مرکزی

**هُما** — پرندهٔ اسطوره‌ای ایرانی که هرگز فرود نمی‌آید و از اوج، همه‌چیز را می‌بیند.
گرهِ بصری: سرستونِ هُمای تخت‌جمشید (عقاب/شیردالِ دو‌سر و متقارن) که **از میله‌های
کندلِ شمعیِ طلایی** ساخته شده باشد — انگار نمودار بازار، بال پرنده شده است.

### پالت

| نقش | رنگ |
|---|---|
| پس‌زمینه | ذغالی بسیار تیره `#0E1116` تا `#141A22` (گرادیان ملایم) |
| طلای اصلی | `#EAA300` |
| طلای روشن (های‌لایت) | `#F5C542` |
| کندل صعودی | `#3FB68B` (کم‌رنگ، فرعی) |
| کندل نزولی | `#E5484D` (کم‌رنگ، فرعی) |
| متن | سفید شکسته `#F2F4F7` |

### لحن

مینیمال، هندسی، وکتور-مانند، متقارن، «فین‌تکِ پریمیوم». بدون شلوغی، بدون افکت‌های
براقِ اغراق‌شده، بدون استوک‌فوتو. حسِّ نشانِ یک صرافیِ کوانت، نه یک اپِ قمار.

</div>

---

## 1) LOGO — copy-paste prompt (English)

```
A minimalist geometric emblem logo for a quantitative trading tool called "HOMA".
The mark is the ancient Persian Homa bird — the symmetrical double-headed
eagle-griffin capital from Persepolis — reconstructed entirely out of golden
candlestick chart bars (thin wicks + rectangular bodies) that fan out to form the
wings and the two facing heads. Perfectly bilaterally symmetric, front-facing,
enclosed in an implied circle.

Style: flat vector, clean straight lines, sharp geometry, single-weight strokes,
subtle 2-tone gold (#EAA300 base, #F5C542 highlights) on a near-black charcoal
background (#0E1116). A few candle bars tinted muted teal (#3FB68B) and muted red
(#E5484D) as small accents. No text, no lettering. No gradients on the bird
itself, only crisp shapes. High contrast, iconic at 32px, premium fintech
identity, centered, generous padding. 1024x1024, square.
```

نکته: اگر خروجی شلوغ شد، در ادامه بنویس: `simpler, fewer candle bars, more negative space, thicker minimal strokes`.

---

## 2) BANNER — copy-paste prompt (English)

```
A wide horizontal hero banner (1500x400, ~4:1) for the GitHub README of a
MetaTrader 5 ↔ Python trading bridge called "HOMA".

Left third: the HOMA emblem — the symmetrical Persian Homa bird (Persepolis
double-headed griffin capital) built from golden candlestick bars, glowing
softly. Center-to-right: the same golden candlestick bars flow out of the bird's
wing and stretch across the banner as a sleek market chart line rising gently
toward the top-right, leaving lots of clean dark space above it for a title
overlay.

Palette: deep charcoal-to-navy gradient background (#0E1116 → #141A22), gold
(#EAA300 / #F5C542) as the dominant accent, small muted teal (#3FB68B) and red
(#E5484D) candles. Thin faint grid lines in the background like a trading
terminal, very low opacity. Flat, geometric, minimal, premium, cinematic but
uncluttered. Leave the upper area mostly empty for text. No text in the image
itself. No stock-photo people, no 3D bevels, no lens flares.
```

<div dir="rtl">

### بعد از ساخت

۱. فایل‌ها را با همین نام‌ها ذخیره کن: `assets/logo.png` و `assets/banner.png`.
۲. در ریشهٔ پروژه: `mkdir -p assets && mv ~/Downloads/logo.png ~/Downloads/banner.png assets/`
۳. لوگو را در تنظیمات مخزن گیت‌هاب به‌عنوان *Social preview* هم آپلود کن.
۴. README خودش `assets/banner.png` را از بالای صفحه لود می‌کند — نیازی به تغییر متن نیست.

### نام‌های جایگزین (اگر «هُما» را نخواستی)

| نام | معنی / حس |
|---|---|
| **Homa Bridge** ✅ | پرندهٔ اقبال + پلِ MT5↔Python (انتخاب فعلی) |
| Homa Deck | «عرشهٔ فرماندهیِ» معاملات |
| Shahin | شاهین — نگاهِ تیزبین از بالا |
| Zarin | زرین/طلایی — تمرکز روی طلا |

</div>
