# Catalogue des statistiques

Genere depuis `pokertracker/core/stats/definitions.py`.

Chaque statistique est le rapport entre un compteur d'action et un compteur
d'opportunite, cumules main par main a l'import. L'echantillon affiche dans
l'interface est toujours celui du denominateur.

## General

| Code | Libelle | Numerateur | Denominateur | Description |
|------|---------|------------|--------------|-------------|
| `hands` | Mains | `hands` | `hands` | Nombre de mains observees pour ce joueur. |
| `bb100` | bb/100 | `bb_net` | `hands` | Gain moyen en grosses blindes pour 100 mains. |
| `net` | Gains | `amount_net` | `hands` | Gain net cumule dans la devise de la table. |
| `wr_hands` | % mains gagnees | `hands_won` | `hands` | Pourcentage de mains remportees. |

## Preflop

| Code | Libelle | Numerateur | Denominateur | Description |
|------|---------|------------|--------------|-------------|
| `vpip` | VPIP | `vpip` | `vpip_opp` | Voluntarily Put money In Pot: frequence d'entree volontaire dans le pot. |
| `pfr` | PFR | `pfr` | `pfr_opp` | Pre-Flop Raise: frequence de relance preflop. |
| `vpip_pfr` | VPIP/PFR gap | `vpip+pfr` | `vpip_opp` | Ecart passif/agressif preflop (indicatif). |
| `rfi` | RFI | `rfi` | `rfi_opp` | Open raise quand le pot est encore non ouvert. |
| `limp` | Limp | `limp` | `limp_opp` | Suivre la grosse blinde sans relancer, pot non ouvert. |
| `limp_fold` | Limp/Fold | `limp_fold` | `limp` | Limper puis se coucher face a une relance. |
| `limp_call` | Limp/Call | `limp_call` | `limp` | Limper puis payer une relance. |
| `iso` | Iso raise | `iso_raise` | `iso_opp` | Relance d'isolement face a un ou plusieurs limpers. |
| `cc` | Cold call | `cold_call` | `cold_call_opp` | Payer une relance sans avoir encore investi volontairement. |
| `3bet` | 3Bet | `three_bet` | `three_bet_opp` | Sur-relance face a une premiere relance. |
| `4bet` | 4Bet | `four_bet` | `four_bet_opp` | Relance du relanceur initial face a un 3bet. |
| `cold4bet` | Cold 4Bet | `cold_4bet` | `cold_4bet_opp` | 4bet sans avoir participe a l'action precedente. |
| `5bet` | 5Bet | `five_bet` | `five_bet_opp` | Relance face a un 4bet. |
| `f3bet` | Fold to 3Bet | `fold_to_3bet` | `fold_to_3bet_opp` | Frequence d'abandon de l'open raise face a un 3bet. |
| `c3bet` | Call 3Bet | `call_3bet` | `fold_to_3bet_opp` | Frequence de call de l'open raiser face a un 3bet. |
| `f4bet` | Fold to 4Bet | `fold_to_4bet` | `fold_to_4bet_opp` | Frequence d'abandon du 3bet face a un 4bet. |
| `squeeze` | Squeeze | `squeeze` | `squeeze_opp` | 3bet face a une relance suivie d'au moins un call. |
| `steal` | ATS | `steal` | `steal_opp` | Attempt To Steal: open raise depuis CO/BTN/SB pot non ouvert. |
| `fsteal` | Fold vs steal | `fold_to_steal` | `fold_to_steal_opp` | Frequence d'abandon des blindes face a une tentative de vol. |
| `resteal` | Resteal | `resteal` | `resteal_opp` | 3bet des blindes face a une tentative de vol. |
| `callsteal` | Call vs steal | `call_vs_steal` | `fold_to_steal_opp` | Call des blindes face a une tentative de vol. |

## Postflop

| Code | Libelle | Numerateur | Denominateur | Description |
|------|---------|------------|--------------|-------------|
| `cbet_f` | CBet F | `cbet_f` | `cbet_opp_f` | Continuation bet de l'agresseur de la street precedente (flop) |
| `cbet_t` | CBet T | `cbet_t` | `cbet_opp_t` | Continuation bet de l'agresseur de la street precedente (turn) |
| `cbet_r` | CBet R | `cbet_r` | `cbet_opp_r` | Continuation bet de l'agresseur de la street precedente (river) |
| `fcbet_f` | Fold CB F | `fold_to_cbet_f` | `fold_to_cbet_opp_f` | Abandon face au continuation bet (flop) |
| `fcbet_t` | Fold CB T | `fold_to_cbet_t` | `fold_to_cbet_opp_t` | Abandon face au continuation bet (turn) |
| `fcbet_r` | Fold CB R | `fold_to_cbet_r` | `fold_to_cbet_opp_r` | Abandon face au continuation bet (river) |
| `rcbet_f` | Raise CB F | `raise_cbet_f` | `fold_to_cbet_opp_f` | Relance du continuation bet (flop) |
| `rcbet_t` | Raise CB T | `raise_cbet_t` | `fold_to_cbet_opp_t` | Relance du continuation bet (turn) |
| `rcbet_r` | Raise CB R | `raise_cbet_r` | `fold_to_cbet_opp_r` | Relance du continuation bet (river) |
| `donk_f` | Donk F | `donk_f` | `donk_opp_f` | Mise dans l'agresseur avant qu'il ne parle (flop) |
| `donk_t` | Donk T | `donk_t` | `donk_opp_t` | Mise dans l'agresseur avant qu'il ne parle (turn) |
| `donk_r` | Donk R | `donk_r` | `donk_opp_r` | Mise dans l'agresseur avant qu'il ne parle (river) |
| `probe_f` | Probe F | `probe_f` | `probe_opp_f` | Mise apres que l'agresseur a renonce a miser (flop) |
| `probe_t` | Probe T | `probe_t` | `probe_opp_t` | Mise apres que l'agresseur a renonce a miser (turn) |
| `probe_r` | Probe R | `probe_r` | `probe_opp_r` | Mise apres que l'agresseur a renonce a miser (river) |
| `dcbet_f` | Delayed CB F | `dcbet_f` | `dcbet_opp_f` | Continuation bet retarde apres une street checkee (flop) |
| `dcbet_t` | Delayed CB T | `dcbet_t` | `dcbet_opp_t` | Continuation bet retarde apres une street checkee (turn) |
| `dcbet_r` | Delayed CB R | `dcbet_r` | `dcbet_opp_r` | Continuation bet retarde apres une street checkee (river) |
| `fbet_f` | Fold vs bet F | `fold_to_bet_f` | `fold_to_bet_opp_f` | Abandon face a une mise (flop) |
| `fbet_t` | Fold vs bet T | `fold_to_bet_t` | `fold_to_bet_opp_t` | Abandon face a une mise (turn) |
| `fbet_r` | Fold vs bet R | `fold_to_bet_r` | `fold_to_bet_opp_r` | Abandon face a une mise (river) |
| `xr_f` | Check-raise F | `checkraise_f` | `checkraise_opp_f` | Check-raise (flop) |
| `xr_t` | Check-raise T | `checkraise_t` | `checkraise_opp_t` | Check-raise (turn) |
| `xr_r` | Check-raise R | `checkraise_r` | `checkraise_opp_r` | Check-raise (river) |
| `af` | AF | `bet_f+raise_f+bet_t+raise_t+bet_r+raise_r` | `call_f+call_t+call_r` | Aggression Factor: (mises + relances) / calls postflop. |
| `afq` | AFq | `bet_f+raise_f+bet_t+raise_t+bet_r+raise_r` | `bet_f+raise_f+bet_t+raise_t+bet_r+raise_r+call_f+call_t+call_r+fold_f+fold_t+fold_r` | Frequence d'agression postflop. |
| `wwsf` | WWSF | `wwsf` | `wwsf_opp` | Won When Saw Flop: pot gagne apres avoir vu le flop. |
| `sawflop` | Saw flop | `saw_flop` | `hands` | Frequence a laquelle le joueur voit le flop. |

## Showdown

| Code | Libelle | Numerateur | Denominateur | Description |
|------|---------|------------|--------------|-------------|
| `wtsd` | WTSD | `wtsd` | `wtsd_opp` | Went To ShowDown apres avoir vu le flop. |
| `wsd` | W$SD | `wsd` | `wsd_opp` | Won money at ShowDown. |
