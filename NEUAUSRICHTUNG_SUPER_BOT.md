# Super-Bot Neuausrichtung — Befunde & Entscheidungen (2026-07-25)

Vollständige Sicherung dessen, was in der Analyse-Session generiert und gesehen wurde.

## Ausgangslage
- Super-Bot machte **4 Wochen keine Trades**. Balance $66.581 (Paper, davon ~95% Restart-Artefakt vor dem Persistenz-Fix), 35 Trades total, −$1.603 realisiert.
- User-Bewertung: unrealistisches Kapital + Bot handelt nichts → Zeit für Neuausrichtung.

## Diagnose — warum nichts gekauft wurde (3 Schichten)
1. **yfinance-NaN-Bug (der Killer, GEFIXT):** seit ~30.06. hängt `yf.download()` eine leere NaN-Kerze an. Effekt: RSI defaultet auf 100, MA/MACD/Supertrend/Ichimoku kippen alle auf „bear" → Score 6–24% → nie über Schwelle → 0 Trades. Fix: `df = df.dropna()`. Beweis: Hand-RSI XLK 47 statt 100. (3. yfinance-Vorfall dieser Klasse — stiller `except Exception: return None`.)
2. **ML-Gate Eigentor (DEAKTIVIERT):** RandomForest auf 35 Trades (20% WR) lernte „alles verliert" → 46 ML-Skips. Gate jetzt `if _ml_trained_count >= 100` → aus bis 100 saubere Trades da sind.
3. **Struktur:** long-only Trend-Following auf 10 Sektor-ETFs mit 8 gestapelten Vetos → handelsarm by design; verpasst Bull-Beta systematisch. Der Bot liest ohnehin Einzelaktien-Signale (Congress, Insider-Form-4, VIP-News) und presst sie in stumpfe ETFs → Auflösung verschenkt.

## Mike the Pirate — objektive Bewertung (Annahme widerlegt)
- **KEIN Trading-Signalgeber.** Co-Host von Paul Brandenburgs deutschem Krypto-/Privacy-Podcast „Nacktes Geld". Verkauft Privacy-E-Books (No-KYC Krypto, anonyme Karten, unsichtbares Telefon). Telegram-Community „Nackte Mark"/NAKMAK (~4000).
- Kein Track-Record, keine Rendite-Claims, keine Aktien-Empfehlungen. Zitat: „Was Mike nicht selbst getestet hat, empfiehlt er nicht" — getestet = Privacy-Tools.
- Assoziierter **Meme-Coin „Nackte Mark" (NAKMAK)**: Influencer + Community bewerben eigenen Token = Follower sind Exit-Liquidität. Erwartungswert klar negativ.
- **Verdikt:** kein Trading-Edge. Sein Thema = Geld *verstecken*, nicht *vermehren*. Instagram-Post nicht lesbar (IG blockt). Entscheidung: **abwarten/beobachten, evtl. Lehren** — nicht kaufen.

## Strategie-Optionen (nach Evidenz sortiert)
| Ansatz | Evidenz | Urteil |
|---|---|---|
| Insider-Cluster (SEC Form 4) | bester belegter Retail-Edge, Daten frei (EDGAR) | **Top-Kandidat** für neues Signal |
| Congress-Copy (NANC) | +88% seit 2023, aber ~Tech-Beta, risk-adj. kein Edge, 45-Tage-Lag | Beimischung ok |
| Momentum 12-1 | robust; Bot macht das schon, aber verwässert auf 10 ETFs | entschlacken + Einzelaktien |
| Options-Flow / Signal-Kanäle | unbelegt | erst messen (Telegram-Pipeline) |
| Buy&Hold / Index | schlägt ~90% aktiver Ansätze | der Maßstab |

## Broker
- **Alpaca (Retail):** nur US-Aktien/ETFs/Optionen/Krypto. Reicht für Einzel-US-Aktien SOFORT — kein Wechsel nötig.
- **IBKR:** ~150 Märkte (US, Xetra, London, Asien), Aktien+Optionen+Futures+Forex, IBKR Irland, echte APIs + kostenloses Paper. Nötig für „gesamte Aktienwelt". MCP-Connector in dieser Umgebung verfügbar.

## ENTSCHEIDUNGEN (User, 2026-07-25)
1. **Super-Bot auf $5000 resetten** (realistisch, wie Crypto 09.07.) — inkl. Risk-Re-Baseline. ✅ umgesetzt
2. **Super-Bot grundlegend neu ausrichten:** ALLE verfügbaren Aktien (Alpaca-Universum) statt 10 ETFs.
3. **IBKR als Clone** parallel (Herausforderer, testet Broker + globales Universum).
4. **Telegram-Pipeline (Telethon)** bauen — Signale messen, nie blind handeln.
5. **NAKMAK:** abwarten, evtl. Lehren.
6. ML-Gate aus ✅, NaN-Fix drin ✅.

## Architektur-Plan All-Stocks (Funnel, analog DEX-Monitor)
Alpaca hat ~5000+ handelbare US-Aktien → nicht jede jeden Zyklus TA-scannbar. Zweistufig:
- **Stufe 1 (breit, billig, täglich):** Liquiditäts-/Volumen-/Momentum-Screen über das ganze Universum → Shortlist ~50–100 Kandidaten. Plus signal-nominiert (Congress/Insider/VIP-News liefern Namen direkt).
- **Stufe 2 (teuer, je Zyklus):** volle 7-Indikator-TA + Sentiment nur auf die Shortlist.
- **Clone-Setup:** Alpaca-Einzelaktien (Kontrolle) vs. IBKR-Einzelaktien (Herausforderer, global-fähig).

## Nächste Schritte
- [x] NaN-Fix + ML-aus deployed
- [x] $5000-Reset + Risk-Re-Baseline
- [ ] All-Stocks-Funnel-Architektur (Universum-Fork noch zu bestätigen)
- [ ] IBKR-Paper-Konto + Connector anbinden
- [ ] Telegram-Telethon-Session (API-Keys von my.telegram.org nötig)
