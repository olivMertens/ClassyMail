/**
 * Mermaid Diagram Viewer - Adds zoom and download capabilities to diagrams
 * Usage: Add this script to markdown viewers that support Mermaid
 */

(function () {
    'use strict';

    // CSS Styles
    const styles = `
        <style>
            .mermaid-wrapper {
                position: relative;
                margin: 20px 0;
                border: 1px solid #e1e4e8;
                border-radius: 6px;
                padding: 16px;
                background-color: white;
                transition: border-color 0.2s;
            }
            .mermaid-wrapper:hover {
                border-color: #0366d6;
            }
            .mermaid-controls {
                position: absolute;
                top: 8px;
                right: 8px;
                display: flex;
                flex-direction: row;
                gap: 4px;
                background: rgba(255, 255, 255, 0.95);
                border: 1px solid #e1e4e8;
                border-radius: 6px;
                padding: 4px;
                opacity: 0.1;
                transition: opacity 0.2s ease-in-out;
                box-shadow: 0 2px 4px rgba(0,0,0,0.05);
                z-index: 10;
            }
            .mermaid-wrapper:hover .mermaid-controls {
                opacity: 1;
            }
            .mermaid-btn {
                padding: 6px 10px;
                font-size: 14px;
                border: none;
                border-radius: 4px;
                background: transparent;
                cursor: pointer;
                transition: all 0.2s;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                color: #586069;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
                font-weight: 500;
            }
            .mermaid-btn:hover {
                background: #f1f8ff;
                color: #0366d6;
            }
            .mermaid-btn i {
                font-style: normal;
                margin-right: 0;
            }
            /* Tooltip */
            .mermaid-btn[data-title]:hover::after {
                content: attr(data-title);
                position: absolute;
                bottom: -30px;
                left: 50%;
                transform: translateX(-50%);
                background: #24292e;
                color: white;
                padding: 4px 8px;
                border-radius: 4px;
                font-size: 12px;
                white-space: nowrap;
                z-index: 20;
                pointer-events: none;
            }
            .mermaid-modal {
                display: none;
                position: fixed;
                z-index: 9999;
                left: 0;
                top: 0;
                width: 100%;
                height: 100%;
                background: rgba(255, 255, 255, 0.95);
                overflow: hidden;
                cursor: grab;
            }
            .mermaid-modal.active {
                display: flex;
                align-items: center;
                justify-content: center;
            }
            .mermaid-modal-content {
                position: relative;
                max-width: 90%;
                max-height: 90%;
                overflow: visible;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .mermaid-modal-close {
                position: fixed;
                top: 20px;
                right: 20px;
                font-size: 30px;
                font-weight: bold;
                color: #586069;
                cursor: pointer;
                background: white;
                border: 1px solid #e1e4e8;
                width: 44px;
                height: 44px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 10001;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                transition: transform 0.2s;
            }
            .mermaid-modal-close:hover {
                color: #cb2431;
                background: #ffeef0;
                border-color: #cb2431;
                transform: scale(1.1);
            }
            /* Pan/Zoom Controls in Modal */
             .mermaid-zoom-controls {
                position: fixed;
                bottom: 30px;
                right: 30px;
                display: flex;
                gap: 8px;
                z-index: 10001;
            }
            .zoom-btn {
                width: 40px;
                height: 40px;
                border-radius: 50%;
                border: 1px solid #e1e4e8;
                background: white;
                color: #586069;
                font-size: 20px;
                cursor: pointer;
                display: flex;
                justify-content: center;
                align-items: center;
                box-shadow: 0 4px 12px rgba(0,0,0,0.1);
                transition: all 0.2s;
            }
            .zoom-btn:hover {
                background: #0366d6;
                color: white;
                border-color: #0366d6;
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
        const clonedSvg = svg.cloneNode(true);
        // Ensure white background for transparency issues
        clonedSvg.style.backgroundColor = 'white';
        const blob = new Blob([clonedSvg.outerHTML], { type: 'image/svg+xml' });
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

        // Add padding
        const padding = 20;
        const width = bbox.width + padding * 2;
        const height = bbox.height + padding * 2;

        const scale = 3; // High res
        canvas.width = width * scale;
        canvas.height = height * scale;

        const ctx = canvas.getContext('2d');
        ctx.scale(scale, scale);

        // White background
        ctx.fillStyle = 'white';
        ctx.fillRect(0, 0, width, height);

        // Draw image
        const img = new Image();
        const svgData = new XMLSerializer().serializeToString(svg);
        const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
        const url = URL.createObjectURL(svgBlob);

        img.onload = function () {
            ctx.drawImage(img, padding, padding);
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

    // Modal with simple Pan/Zoom capabilities
    let currentScale = 1;
    let isDragging = false;
    let startX, startY, translateX = 0, translateY = 0;

    function resetZoom() {
        currentScale = 1;
        translateX = 0;
        translateY = 0;
    }

    function showZoomModal(svg) {
        resetZoom();

        const modal = document.createElement('div');
        modal.className = 'mermaid-modal active';

        // Clone SVG for modal
        const modalSvg = svg.cloneNode(true);
        modalSvg.style.transition = 'transform 0.1s ease-out';
        modalSvg.style.cursor = 'grab';
        modalSvg.removeAttribute('height'); // Allow full scaling
        modalSvg.removeAttribute('width');
        modalSvg.style.maxHeight = '90vh';
        modalSvg.style.maxWidth = '90vw';

        modal.innerHTML = `
            <div class="mermaid-modal-content"></div>
            <button class="mermaid-modal-close" title="Close (Esc)">&times;</button>
            <div class="mermaid-zoom-controls">
                <button class="zoom-btn" id="zoom-out" title="Zoom Out">-</button>
                <button class="zoom-btn" id="zoom-reset" title="Reset">⟲</button>
                <button class="zoom-btn" id="zoom-in" title="Zoom In">+</button>
            </div>
        `;

        document.body.appendChild(modal);
        const content = modal.querySelector('.mermaid-modal-content');
        content.appendChild(modalSvg);

        // Close logic
        const close = () => {
            modal.remove();
            document.removeEventListener('keydown', escHandler);
        };
        modal.querySelector('.mermaid-modal-close').onclick = close;

        const escHandler = (e) => { if (e.key === 'Escape') close(); };
        document.addEventListener('keydown', escHandler);

        // Zoom Logic
        const updateTransform = () => {
            modalSvg.style.transform = `translate(${translateX}px, ${translateY}px) scale(${currentScale})`;
        };

        modal.querySelector('#zoom-in').onclick = (e) => {
            e.stopPropagation();
            currentScale *= 1.2;
            updateTransform();
        };

        modal.querySelector('#zoom-out').onclick = (e) => {
            e.stopPropagation();
            currentScale /= 1.2;
            updateTransform();
        };

        modal.querySelector('#zoom-reset').onclick = (e) => {
            e.stopPropagation();
            resetZoom();
            updateTransform();
        };

        // Pan Logic (Mouse)
        modal.onmousedown = (e) => {
            if (e.target.closest('.zoom-btn') || e.target.closest('.mermaid-modal-close')) return;
            isDragging = true;
            startX = e.clientX - translateX;
            startY = e.clientY - translateY;
            modalSvg.style.cursor = 'grabbing';
        };

        document.onmousemove = (e) => {
            if (!isDragging) return;
            e.preventDefault();
            translateX = e.clientX - startX;
            translateY = e.clientY - startY;
            updateTransform();
        };

        document.onmouseup = () => {
            isDragging = false;
            modalSvg.style.cursor = 'grab';
        };

        // Wheel Zoom
        modal.onwheel = (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            currentScale *= delta;
            updateTransform();
        };
    }

    // Add controls to a Mermaid diagram
    function addControlsToDiagram(container, index) {
        const svg = container.querySelector('svg');
        if (!svg) return;

        // Wrap diagram if not already wrapped
        if (!container.parentNode.classList.contains('mermaid-wrapper')) {
            const wrapper = document.createElement('div');
            wrapper.className = 'mermaid-wrapper';
            container.parentNode.insertBefore(wrapper, container);
            wrapper.appendChild(container);

            // Create controls
            const controls = document.createElement('div');
            controls.className = 'mermaid-controls';
            controls.innerHTML = `
                <button class="mermaid-btn mermaid-zoom" data-title="Fullscreen & Zoom">
                    ⤢
                </button>
                <div style="width: 1px; height: 16px; background: #e1e4e8; margin: 0 4px;"></div>
                <button class="mermaid-btn mermaid-download-svg" data-title="Download SVG">
                    SVG
                </button>
                <button class="mermaid-btn mermaid-download-png" data-title="Download PNG">
                    PNG
                </button>
            `;

            wrapper.appendChild(controls);

            // Event listeners
            controls.querySelector('.mermaid-zoom').onclick = () => showZoomModal(svg);
            controls.querySelector('.mermaid-download-svg').onclick = () => downloadSVG(svg, `diagram-${index + 1}.svg`);
            controls.querySelector('.mermaid-download-png').onclick = () => downloadPNG(svg, `diagram-${index + 1}.png`);
        }
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
