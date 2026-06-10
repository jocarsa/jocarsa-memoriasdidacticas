# Jocarsa | Memoria didáctica multiusuario

Estructura:

```text
jocarsa-memoriadidactica/
├── index.html
├── style.css
├── app.js
├── api.php
└── xls/
    ├── importar_multiusuario.py
    ├── *.xls
    └── grades.sqlite
```


Dependencias:

```bash
sudo apt install php-sqlite3
pip install pandas xlrd openpyxl lxml html5lib beautifulsoup4
```

Importar desde la carpeta `xls`:

```bash
python3 importar_multiusuario.py --reset
```

O asignar directamente a un usuario:

```bash
python3 importar_multiusuario.py --reset --user jocarsa
```

El administrador puede crear usuarios desde el botón **Usuarios**.
