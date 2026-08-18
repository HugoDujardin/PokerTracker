# Construction de l'executable Windows

`build_windows.ps1` cree un environnement virtuel, installe les dependances,
lance les tests puis produit `dist\PokerTracker\PokerTracker.exe` avec
PyInstaller.

Prerequis: Windows 10/11 64 bits, Python 3.10 ou plus recent
(https://www.python.org/downloads/windows/, cocher « Add python.exe to PATH »).

```powershell
git clone <depot> PokerTracker
cd PokerTracker
.\packaging\build_windows.ps1
```

Le dossier `dist\PokerTracker` est autonome: il peut etre copie sur une autre
machine Windows sans Python installe. La base de donnees et la configuration
restent dans `%APPDATA%\PokerTracker`, elles ne sont donc pas ecrasees par une
mise a jour du programme.

## Demarrage automatique avec Windows

Creer un raccourci vers `PokerTracker.exe` dans
`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.
