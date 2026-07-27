# cc-quota-guard

Claude Code'u **kota-farkındalıklı** çalıştırır: verdiğin yüzde eşiklerine
gelince işi güvenli bir noktada durdurur, ilerlemeyi diske yazar ve kota
**reset olunca kaldığı yerden otomatik devam eder**.

*[English README.md](README.md)*

> Bu dosya İngilizce ana README'nin Türkçe çevirisidir; proje kodu, hook
> mesajları ve GitHub üzerindeki birincil dokümantasyon İngilizcedir.

## Çözdüğü sorun

Normalde limit dolduğu an Claude Code aniden durur — neredeyse, yarım kalmış
düzenlemeler, hiçbir kayıt olmadan. Bu araç limite *toslamadan önce*, siz
hangi noktada ve nasıl durmasını istiyorsanız öyle durur:

- **YUMUŞAK eşik** (varsayılan 5 saatlik session'ın %80'i): hâlâ pay var —
  Claude mevcut todo maddesini bitirir, sonra temiz kapanış yapar (commit +
  ilerleme notu) ve durur.
- **SERT eşik** (varsayılan %95 session / %98 haftalık): madde ortasında bile
  tetiklenebilir, çünkü o noktada güvenle bitirecek pay kalmamış olabilir.
  **Varsayılan olarak kapalı.** Açarsanız, Claude'un o maddede yaptığı
  değişiklikler `git stash` ile geri alınır, madde tekrar `pending` olur ve
  reset sonrası sıfırdan yapılır. 8 maddelik bir listede 6. madde yarıda sert
  eşiğe çarparsa: 6.'nın yaptığı iş stash'e taşınır, reset olur, 6. sıfırdan
  yapılır, 7-8 normal devam eder.

## Kurulum

**Önerilen — Claude Code plugin'i olarak:**

```
/plugin marketplace add BunyaminGP/cc-quota-guard
/plugin install cc-quota-guard
```

Bu kadar — elle dosya kopyalama yok, `settings.json` düzenleme yok. Hook'lar
otomatik kaydolur ve o andan itibaren her oturumu korumaya başlar.

**Not:** bir plugin'in `bin/` klasörü sadece Claude'un **kendi** iç Bash tool
çağrıları için PATH'e ekleniyor — sizin terminalinize değil. `cc-run` sizin
çalıştırmanız için var (headless, kendi kendine devam eden bir Claude
çalışması başlatan şey o), o yüzden onu kendi shell'inizden düz `cc-run`
komutuyla çağırabilmek için küçük bir ek adım gerekiyor — aşağıdaki
[cc-run'ı kendi terminalinizden kullanma](#cc-runı-kendi-terminalinizden-kullanma)
bölümüne bakın. Hook'ların kendisi (asıl kota koruması) buna ihtiyaç
duymuyor — plugin kurulur kurulmaz zaten çalışıyor.

Takımınızla version control üzerinden paylaşmak isterseniz user yerine
project scope'una kurun:

```
claude plugin install cc-quota-guard --scope project
```

### Yapılandırma ekranı

Plugin'i etkinleştirdiğinizde Claude Code size eşikleri sorar — aracın
gerçek "ayarlar ekranı" bu, plugin'in `userConfig` alanı üzerinden
tanımlanıyor:

- **Yumuşak eşik — session (%)** — varsayılan 80
- **Sert eşik — session (%)** — varsayılan 95
- **Sert eşik — haftalık (%)** — varsayılan 98
- **Sert eşikte otomatik geri almayı (git stash) aç** — varsayılan kapalı

Sonradan, yeniden kurmadan değiştirmek için:

```
claude plugin install cc-quota-guard --config session_soft=70 --config hard_abort_enabled=true
```

(değiştirmek istediğiniz her alan için `--config key=value` tekrarlayın),
ya da bir oturum içinde `/plugin` yazıp plugin için "configure" seçeneğini
kullanın. Değerler plugin'in dosyalarında değil, kendi
`~/.claude/settings.json`'ınızda `pluginConfigs` altında saklanır.

**Fallback — manuel kurulum** (plugin sistemi olmayan eski Claude Code
sürümleri için):

```bash
git clone https://github.com/BunyaminGP/cc-quota-guard
cd cc-quota-guard
bash install.sh
```

Bu, aracı `~/.claude/cc-quota-guard/` altına kopyalar ve `PostToolUse`
hook'larını `~/.claude/settings.json`'a merge eder (idempotent — güncelleme
için tekrar çalıştırmak güvenli).

## cc-run'ı kendi terminalinizden kullanma

`cc-run`'ın kendi shell'inizde düz komut olarak çalışması için bir kerelik
kurulum (hook'lar/koruma için gerekli değil — sadece `cc-run` wrapper'ının
kendisi için):

**Windows / PowerShell:**

```powershell
Get-Content shell\cc-run.ps1 | Add-Content $PROFILE
. $PROFILE
```

(Git for Windows gerektirir, Git Bash için — `cc-run` bir bash script'i,
PowerShell onu direkt çalıştıramaz). Bu, plugin'in güncel kurulum yolunu her
çağrıda yeniden bulan bir `cc-run` fonksiyonu tanımlar, plugin güncellemeleri
sonrası bozulmaz.

**macOS / Linux:**

```bash
cat shell/cc-run.sh >> ~/.bashrc   # ya da ~/.zshrc
source ~/.bashrc
```

Aynı mantık — her çağrıda plugin'in kurulum yolunu yeniden bulan bir shell
fonksiyonu. Plugin sistemi yerine manuel `install.sh` fallback'ini
kullandıysanız zaten sabit bir yolunuz var:
`~/.claude/cc-quota-guard/bin/cc-run` — sadece `~/.local/bin`'in (
`install.sh`'ın sembolik link koyduğu yer) `PATH`'inizde olduğundan emin
olun, bu adımı atlayabilirsiniz.

## Kullanım

Tam otomatik (dur + reset'te otomatik devam):

```bash
cc-run "auth servisini 3 adımda refactor et: ..."
cc-run --threshold 80 --session-hard 95 --weekly-hard 98 @gorev.md
```

- `--threshold N` — session **YUMUŞAK** eşiği (varsayılan 80). Madde biter,
  sonra durur.
- `--session-hard N` — session **SERT** eşiği (varsayılan 95). Madde
  ortasında tetiklenebilir.
- `--weekly-hard N` — haftalık **SERT** eşik (varsayılan 98). Madde
  ortasında tetiklenebilir.
- `--enable-hard-abort` — SERT eşik tetiklendiğinde madde ortasındaki işi
  otomatik geri almayı (`git stash`) etkinleştirir. **Bu bayrağı vermezseniz
  kapalıdır.** Vermezseniz SERT eşik de YUMUŞAK gibi sadece temiz kapanışa
  zorlar — hiçbir şey otomatik dokunulmaz. Açmadan önce aşağıdaki
  [Güvenlik](#güvenlik--hard-abort-açmadan-önce-okuyun) bölümünü okuyun.
- Görev: düz metin ya da `@dosya.md`.

Sadece "temiz dur" (wrapper'sız, etkileşimli oturum): hook'lar kurulu olduğu
için normal `claude` oturumu da eşiklere gelince durur — ama otomatik devam
etmez, reset sonrası `claude -c`'yi kendiniz çalıştırırsınız. Bu modda
eşikleri ortam değişkeniyle verin: `CC_SESSION_SOFT=80 CC_SESSION_HARD=95
CC_WEEKLY_HARD=98`, geri almayı açmak için `CC_HARD_ABORT=1`.

## Nasıl çalışır

1. **Hook** (`scripts/quota_gate.py`) — iki `PostToolUse` matcher'ına takılı:
   - `TodoWrite`: hangi maddenin `in_progress` olduğunu ve hangi commit'ten
     başladığını `.cc-quota/todos_state.json`'a kaydeder; YUMUŞAK eşiği
     kontrol eder.
   - `*` (tüm araçlar): SERT eşikleri **her** çağrıda kontrol eder. Bir
     maddenin içindeki iş (birçok Edit/Bash/Write çağrısı) tek bir
     `TodoWrite`'tan sonra uzun sürebilir; sadece `TodoWrite`'ta bakmak bir
     kota patlamasını çok geç fark ettirir.
2. **State dosyaları**
   - `.cc-quota/progress.md` — ne bitti, sırada ne var, ve (sert geri alma
     tetiklendiyse) hangi madde geri alındı. Reset sonrası buradan devam
     edilir.
   - `.cc-quota/todos_state.json` — hook'un kendi todo anlık görüntüsü.
3. **Wrapper** (`bin/cc-run`) — Claude'u başlatır; bir eşik onu durdurunca
   `.cc-quota/STOP.json`'daki reset zamanını okur, o zamana kadar uyur,
   `claude -c` ile devam ettirir. `progress.md`'de `CC_QUOTA_DONE` görünce
   durur.

Kota kaynağı: Anthropic'in **dokümante edilmemiş** OAuth usage endpoint'i
(`/api/oauth/usage`) — session (5s) ve haftalık yüzdeleri + reset zamanlarını
verir.

## Güvenlik — hard-abort açmadan önce okuyun

`--enable-hard-abort`, otomatik bir hook'un çalışma ağacınızda sizin
onayınız olmadan `git stash` çalıştırmasına izin verir. Bunu anladıktan
sonra bilerek açmak makul; ama az önce plugin'i kuran birinin **varsayılanı**
olması makul değil. Açmadan önce bilmeniz gerekenler:

- **"Madde başında temiz ağaç" varsayımına dayanır.** `git stash` çalışma
  ağacını son commit'e döndürür. Bunun doğru sonucu vermesi için her
  maddenin bitişinde gerçekten commit atılmış olması gerekir (araç zaten
  buna yönlendiriyor). Önceki madde commit'lenmediyse, stash onu da süpürür
  — kasıtlı değil, bilinen bir sınırlama.
- **Geri döndürülebilir ama otomatik değil.** `git stash` hiçbir şeyi silmez
  — `git stash list` / `git stash pop` ile bakılabilir — ama sizin için
  otomatik geri getirmez. Bu kasıtlı: otomatik bir "geri alma"nın kendisi de
  sessizce yanlış bir şey yapabilirdi.
- **Git yoksa geri alma da yok.** Proje bir git deposu değilse, hard-abort
  sessizce temiz-kapanışa düşer — açmamış gibi davranır.
- **Önce atılabilir bir yerde deneyin.** Gerçek işe güvenmeden önce bir
  scratch repo'da.
- **Bir proje bunu sizin için sessizce açamaz.** `hard_abort_enabled`
  sadece SİZİN kontrol ettiğiniz bir yerden ayarlanabilir — `CC_HARD_ABORT`
  ortam değişkeni ya da plugin'in kendi yapılandırma ekranı. Bilerek
  `.cc-quota/config.json`'dan hiç okunmuyor, çünkü o dosya projenin içinde
  yaşıyor ve klonladığınız bir repoda zaten commit'lenmiş halde gelebilir.
  Sadece yüzde eşikleri proje tarafından ayarlanabilir — onlar sadece NE
  ZAMAN durduğunuzu değiştirir, yıkıcı bir şeyin olup olmayacağını değil.
- **Eski/bırakılmış bir `STOP.json` korumayı sonsuza kadar kapatamaz.** Hook,
  var olan bir `STOP.json`'ı sadece `resets_at` hâlâ gelecekteyken "zaten
  durduk, tekrar kontrol etme" olarak sayıyor. Süresi geçmiş, bozuk ya da
  klonlanan projeyle birlikte gelen biri yok sayılıp temizleniyor — korumayı
  sessizce kapatamıyor.
- **Kendi projenizin `.gitignore`'una `.cc-quota/` ekleyin.** Bu, yerel
  çalışma zamanı durumu (todo anlık görüntüleri, stop işaretçileri) —
  commit'lenecek bir şey değil; izlenmemesi ayrıca gerçek değişikliklerle
  birlikte `git stash`'e sürüklenmesini de önler.

## Gereksinimler

- `bash`, `python3`
- Claude Code CLI (`claude`), Pro/Max aboneliği (usage endpoint sadece bu
  planlarda çalışır)
- `~/.claude/.credentials.json` içinde geçerli bir OAuth token (Claude
  Code'a giriş yapınca otomatik oluşur)
- `--enable-hard-abort` kullanmayı planlıyorsanız git

## Doğrulama / hata ayıklama

```bash
python3 scripts/usage.py          # okunan yüzdeler
python3 scripts/usage.py --probe  # API'nin HAM cevabı (alan adı doğrulama)
```

(Plugin kurulumunda `scripts/` yerine plugin'in kurulu olduğu yolu kullanın —
bir hook içinden `python3 "$CLAUDE_PLUGIN_ROOT/scripts/usage.py"`, ya da
cache yolunu `claude plugin list` ile bulun.)

`--probe` çıktısında `.five_hour.utilization` / `.seven_day.utilization`
görünmüyorsa Anthropic şemayı değiştirmiş olabilir — `scripts/usage.py`
içindeki `_normalize()` fonksiyonundaki alan adlarını güncelleyin.

## Dürüst uyarılar

- **API resmi değil.** `/api/oauth/usage` dokümante edilmemiş; Anthropic
  haber vermeden değiştirebilir/kaldırabilir. Hook **fail-open**: kotayı
  okuyamazsa Claude'u asla durdurmaz. API çökerse koruma sessizce devre dışı
  kalır.
- **Tespit anlık değil.** Hook artık her tool çağrısında tetiklendiği için
  (sadece `TodoWrite`'ta değil) gerçek gecikme kabaca `CC_USAGE_CACHE_TTL`
  kadardır (varsayılan 30sn) — "bir maddenin tamamı"ndan çok daha sıkı, ama
  bu pencere içindeki tek bir çok büyük tool çağrısı yine de bir eşiği
  aşabilir. Eşikleri %100'e değil biraz altına koyun.
- **Makine açık kalmalı.** Wrapper reset'e kadar uyur; bilgisayar
  uyursa/kapanırsa kendiliğinden devam etmez.
- **Bağlam kaybına güvenmeyin.** `claude -c` konuşmayı geri getirir ama tam
  garanti değildir. Gerçek hafıza `progress.md` + git commit'leridir; kritik
  olan her şeyi oraya yazın.
- **`acceptEdits` uyarısı.** Wrapper varsayılan olarak `--permission-mode
  acceptEdits` ile çalışır (reset sonrası sormadan devam edebilsin diye).
  Kabul edilemezse `CC_CLAUDE_ARGS=""` ile kapatıp etkileşimli çalıştırın.
  Güncel bayraklar için `claude --help`'e bakın — zamanla değişebilir.
- **Plan.** Usage endpoint Pro/Max'te çalışır. Farklı bir planda `--probe`
  boş/farklı dönebilir.

## Ayarlar

Eşikleri ayarlayabileceğiniz üç yer var, şu sırayla kontrol edilir —
**her biri altındakini ezer**:

1. **`CC_*` ortam değişkenleri** — açık, tek seferlik override (`cc-run`
   bayraklarını elle verdiğinizde ya da manuel `export` ile)
2. **`.cc-quota/config.json`** (proje bazlı) — `session_soft`,
   `session_hard`, `weekly_hard`, `hard_abort_enabled` anahtarları
3. **Plugin'in yapılandırma ekranı** (yukarıda) — 1 ya da 2'yi vermediğiniz
   her yerde geçerli olan kişisel varsayılanınız

Üçü de hiçbir yerde ayarlanmadıysa sabit varsayılan devreye girer: 80 / 95
/ 98 / geri alma kapalı.

| Değişken | Varsayılan | Açıklama |
|---|---|---|
| `CC_SESSION_SOFT` | 80 | Session YUMUŞAK eşiği (%) — madde biter, sonra durur |
| `CC_SESSION_HARD` | 95 | Session SERT eşiği (%) — madde ortasında tetiklenebilir |
| `CC_WEEKLY_HARD` | 98 | Haftalık SERT eşik (%) — madde ortasında tetiklenebilir |
| `CC_HARD_ABORT` | (kapalı) | SERT eşikte otomatik geri almayı (`git stash`) açar. `cc-run --enable-hard-abort` ile aynı |
| `CC_USAGE_CACHE_TTL` | 30 | Kota cache süresi (sn) — aynı zamanda sert eşik tespit gecikmesi |
| `CC_RESUME_BUFFER` | 60 | Reset sonrası ek bekleme (sn) |
| `CC_CLAUDE_ARGS` | `--permission-mode acceptEdits` | `claude`'a geçilecek ekstra bayraklar |

## Kaldırma

Plugin kurulumu:

```
/plugin uninstall cc-quota-guard
```

Manuel kurulum:

```bash
rm -rf ~/.claude/cc-quota-guard ~/.claude/.cc-quota-cache.json ~/.local/bin/cc-run
# settings.json'dan iki quota_gate.py PostToolUse girdisini elle sil
```

## Katkı

Issue ve PR'lar açık. Kota tespiti ya da geri alma mantığını değiştirirken
"fail-open, yıkıcı olan her şeye opt-in, sınırlamayı belgele" tarzını koruyun
— aracın bütün amacı bu.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
