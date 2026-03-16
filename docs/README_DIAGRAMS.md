# 📊 Interactive Mermaid Diagrams

Tous les diagrammes Mermaid de cette documentation sont interactifs et incluent des contrôles pour zoomer et télécharger.

## Fonctionnalités

Survolez un diagramme pour faire apparaître la barre d'outils flottante (en haut à droite) :

- ⤢ **Plein écran & Zoom** : Ouvre le diagramme dans un modal interactif
    - **Pan** : Cliquer-glisser pour déplacer
    - **Zoom** : Molette souris ou boutons (+ / -)
- **SVG** : Télécharge le diagramme au format vectoriel (transparent)
- **PNG** : Télécharge le diagramme en haute résolution (3x, fond blanc)

## Utilisation dans les viewers Markdown

### GitHub / GitLab
Les diagrammes Mermaid sont rendus automatiquement. Pour les contrôles interactifs, utilisez l'**outil d'export** : [mermaid-export.html](./mermaid-export.html)

### VS Code
Installez l'extension **Markdown Preview Mermaid Support** :
```
code --install-extension bierner.markdown-mermaid
```

Pour activer les contrôles interactifs, ajoutez dans vos settings VS Code :
```json
{
  "markdown.preview.scripts": [
    "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js",
    "./docs/mermaid-viewer.js"
  ]
}
```

### Viewer HTML local
Pour afficher les docs avec contrôles interactifs, créez un fichier HTML :

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Documentation</title>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script src="./mermaid-viewer.js"></script>
    <style>
        body { max-width: 1200px; margin: 40px auto; padding: 20px; font-family: sans-serif; }
    </style>
</head>
<body>
    <div id="content"></div>
    <script>
        mermaid.initialize({ startOnLoad: true, theme: 'default' });

        fetch('./ARCHITECTURE.md')
            .then(r => r.text())
            .then(md => {
                document.getElementById('content').innerHTML = marked.parse(md);
                mermaid.run();
                MermaidViewer.init();
            });
    </script>
</body>
</html>
```

## Raccourcis clavier

Lorsqu'un diagramme est agrandi en mode zoom :
- **ESC** : Fermer le zoom
- **Clic en dehors** : Fermer le zoom

## Formats d'export

### SVG (Vectoriel)
- ✅ Redimensionnable sans perte de qualité
- ✅ Idéal pour les présentations et documents
- ✅ Modifiable dans Inkscape, Illustrator, etc.
- 📦 Taille de fichier petite

### PNG (Raster)
- ✅ Haute résolution (2x pour écrans Retina)
- ✅ Compatible avec tous les outils
- ✅ Fond blanc automatique
- 📦 Taille de fichier moyenne

## Exemple d'intégration

Voir [ARCHITECTURE.md](./ARCHITECTURE.md) pour un exemple complet avec plusieurs diagrammes interactifs.

## Compatibilité

- ✅ Chrome/Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Viewers Markdown modernes
- ⚠️ GitHub/GitLab : utiliser l'outil d'export séparé

## Support

Pour tout problème avec les diagrammes :
1. Vérifier que JavaScript est activé
2. Vérifier que Mermaid.js est chargé
3. Ouvrir la console développeur (F12) pour voir les erreurs
4. Utiliser [mermaid-export.html](./mermaid-export.html) en fallback
