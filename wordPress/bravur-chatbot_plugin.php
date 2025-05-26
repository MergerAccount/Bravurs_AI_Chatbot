<?php
/*
Plugin Name: Bravur AI Chatbot
Description: Loads Bravur AI Chatbot from Python app
Version: 1.2.0
Author: Bravur Team
*/

// Prevent direct access
if (!defined('ABSPATH')) {
    exit;
}

class BravurChatbotPlugin {
    private $api_base_url;

    public function __construct() {
        $this->api_base_url = 'http://localhost:5001/api/v1';
        add_action('wp_footer', array($this, 'add_chatbot_html'));
    }

    public function add_chatbot_html() {
        $api_url = $this->api_base_url;
        ?>
        <div id="bravur-chatbot-container"></div>
        <script>
        // Simple toggle function that will work immediately
        function setupChatbotToggle() {
            const toggleButton = document.getElementById('chatbox-toggle');
            const chatboxInner = document.getElementById('chatbox-inner');

            if (toggleButton && chatboxInner) {
                toggleButton.addEventListener('click', function() {
                    chatboxInner.classList.toggle('chatbox-hidden');
                    const toggleIcon = toggleButton.querySelector('#toggle-icon');
                    if (toggleIcon) {
                        toggleIcon.textContent = chatboxInner.classList.contains('chatbox-hidden') ? '+' : '−';
                    }
                    console.log('Chatbox toggled');
                });
                console.log('Basic toggle functionality initialized');
            }
        }

        document.addEventListener('DOMContentLoaded', function() {
            console.log('Fetching widget from <?php echo esc_js($api_url); ?>/widget');
            fetch('<?php echo esc_js($api_url); ?>/widget')
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok: ' + response.statusText);
                    }
                    return response.text();
                })
                .then(html => {
                    const container = document.getElementById('bravur-chatbot-container');
                    if (!container) {
                        console.error('Container not found');
                        return;
                    }
                    container.innerHTML = html;
                    console.log('Widget HTML injected');

                    // Immediately set up basic toggle functionality
                    setupChatbotToggle();

                    // Load CSS
                    const css = document.createElement('link');
                    css.rel = 'stylesheet';
                    css.href = '<?php echo esc_js($api_url); ?>/widget/css';
                    css.onload = function() {
                        console.log('CSS loaded');
                        // Ensure chatbox is hidden initially
                        const chatboxInner = document.getElementById('chatbox-inner');
                        if (chatboxInner) chatboxInner.classList.add('chatbox-hidden');
                    };
                    document.head.appendChild(css);

                    // Load script.js
                    const consentJs = document.createElement('script');
                    consentJs.src = '<?php echo esc_js($api_url); ?>/widget/js/consent';
                    consentJs.onload = function() {
                        console.log('✅ consent.js loaded');

                        // Initialize consent after both scripts and DOM are ready
                        if (typeof initializeConsent === 'function') {
                            // Wait a tick to ensure DOM is fully ready
                            setTimeout(() => {
                                initializeConsent();
                                console.log('Consent system initialized');
                            }, 50);
                        } else {
                            console.error('initializeConsent function not found');
                        }
                    };
                    scriptJs.onerror = function() {
                        console.error('Failed to load script.js');
                    };
                    document.body.appendChild(scriptJs);
                })
                .catch(error => {
                    console.error('Error fetching widget HTML:', error);
                });
        });
        </script>
        <style>
            /* Basic styles to ensure toggle works */
            #chatbox-inner.chatbox-hidden {
                display: none !important;
            }
            #chatbox-toggle {
                cursor: pointer;
                padding: 10px;
                background: #0073aa;
                color: white;
                border-radius: 5px;
                display: inline-block;
            }
            #toggle-icon {
                margin-left: 5px;
            }
        </style>
        <?php
    }
}

new BravurChatbotPlugin();