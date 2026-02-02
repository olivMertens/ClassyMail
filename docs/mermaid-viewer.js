/**
 * Mermaid Diagram Viewer - Adds zoom and download capabilities to diagrams
 * Usage: Add this script to markdown viewers that support Mermaid
 */

(function () {
    'use strict';

    // CSS Styles
    const styles = `
        <style>
            .mermaid-controls {
                margin-top: 8px;
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }
            .mermaid-btn {
                padding: 6px 12px;
                font-size: 13px;
                border: 1px solid #ddd;
                border-radius: 4px;
                background: white;
                cursor: pointer;
                transition: all 0.2s;
                display: inline-flex;
                align-items: center;
                gap: 4px;
            }
            .mermaid-btn:hover {
                background: #f5f5f5;
                border-color: #0066cc;
            }
            .mermaid-modal {
                display: none;
                position: fixed;
                z-index: 9999;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.9);
                overflow: auto;
            }
            .mermaid-modal.active {
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .mermaid-modal-content {
                position: relative;
                max-width: 95%;
                max-height: 95%;
                background: white;
                padding: 20px;
                border-radius: 8px;
                overflow: auto;
            }
            .mermaid-modal-close {
                position: absolute;
                top: 10px;
                right: 10px;
                font-size: 28px;
                font-weight: bold;
                color: #aaa;
                cursor: pointer;
                background: white;
                border: none;
                width: 35px;
                height: 35px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10000;
            }
            .mermaid-modal-close:hover {
                color: #000;
                background: #f5f5f5;
            }
            .mermaid-wrapper {
                position: relative;
                margin: 20px 0;
            }
        </style>
    `;

    // Add styles to document
    document.head.insertAdjacentHTML('beforeend', styles);

    // Wait for Mermaid to be available
    function waitForMermaid(callback) {
        if (window.mermaid) {
            callback();
        } else {
            setTimeout(() => waitForMermaid(callback), 100);
        }
    }

    // Download SVG
    function downloadSVG(svg, filename = 'diagram.svg') {
        const blob = new Blob([svg.outerHTML], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    // Download PNG
    function downloadPNG(svg, filename = 'diagram.png') {
        const canvas = document.createElement('canvas');
        const bbox = svg.getBBox();
        const scale = 2; // Retina quality
        canvas.width = bbox.width * scale;
        canvas.height = bbox.height * scale;

        const ctx = canvas.getContext('2d');
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, canvas.width, canvas.height);

        const img = new Image();
        const svgBlob = new Blob([svg.outerHTML], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(svgBlob);

        img.onload = function () {
            ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            canvas.toBlob(function (blob) {
                const pngUrl = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = pngUrl;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(pngUrl);
            });
            URL.revokeObjectURL(url);
        };

        img.src = url;
    }

    // Show zoom modal
    function showZoomModal(svg) {
        const modal = document.createElement('div');
        modal.className = 'mermaid-modal active';
        modal.innerHTML = `
            <div class="mermaid-modal-content">
                <button class="mermaid-modal-close">&times;</button>
                ${svg.outerHTML}
            </div>
        `;

        document.body.appendChild(modal);

        const closeBtn = modal.querySelector('.mermaid-modal-close');
        closeBtn.onclick = () => modal.remove();
        modal.onclick = (e) => {
            if (e.target === modal) modal.remove();
        };

        // ESC key to close
        const escHandler = (e) => {
            if (e.key === 'Escape') {
                modal.remove();
                document.removeEventListener('keydown', escHandler);
            }
        };
        document.addEventListener('keydown', escHandler);
    }

    // Add controls to a Mermaid diagram
    function addControlsToDiagram(container, index) {
        const svg = container.querySelector('svg');
        if (!svg) return;

        // Wrap diagram
        const wrapper = document.createElement('div');
        wrapper.className = 'mermaid-wrapper';
        container.parentNode.insertBefore(wrapper, container);
        wrapper.appendChild(container);

        // Create controls
        const controls = document.createElement('div');
        controls.className = 'mermaid-controls';
        controls.innerHTML = `
            <button class="mermaid-btn mermaid-zoom" title="Zoom">
                🔍 Zoom
            </button>
            <button class="mermaid-btn mermaid-download-svg" title="Download SVG">
                📥 SVG
            </button>
            <button class="mermaid-btn mermaid-download-png" title="Download PNG">
                📥 PNG
            </button>
        `;

        wrapper.appendChild(controls);

        // Event listeners
        controls.querySelector('.mermaid-zoom').onclick = () => showZoomModal(svg);
        controls.querySelector('.mermaid-download-svg').onclick = () => downloadSVG(svg, `diagram-${index + 1}.svg`);
        controls.querySelector('.mermaid-download-png').onclick = () => downloadPNG(svg, `diagram-${index + 1}.png`);
    }

    // Initialize all Mermaid diagrams
    function initializeMermaidControls() {
        waitForMermaid(() => {
            // Find all rendered Mermaid diagrams
            const diagrams = document.querySelectorAll('.mermaid, [data-type="mermaid"]');

            diagrams.forEach((diagram, index) => {
                // Check if controls already added
                if (diagram.parentNode?.classList.contains('mermaid-wrapper')) return;

                // Wait for SVG to be rendered
                const checkSVG = setInterval(() => {
                    if (diagram.querySelector('svg')) {
                        clearInterval(checkSVG);
                        addControlsToDiagram(diagram, index);
                    }
                }, 100);

                // Timeout after 5 seconds
                setTimeout(() => clearInterval(checkSVG), 5000);
            });
        });
    }

    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeMermaidControls);
    } else {
        initializeMermaidControls();
    }

    // Re-initialize on dynamic content changes (for SPA frameworks)
    const observer = new MutationObserver((mutations) => {
        const hasMermaid = mutations.some(m =>
            Array.from(m.addedNodes).some(n =>
                n.querySelector?.('.mermaid, [data-type="mermaid"]')
            )
        );
        if (hasMermaid) {
            setTimeout(initializeMermaidControls, 500);
        }
    });

    observer.observe(document.body, { childList: true, subtree: true });

    // Expose public API
    window.MermaidViewer = {
        init: initializeMermaidControls,
        downloadSVG,
        downloadPNG,
        showZoom: showZoomModal
    };
})();
