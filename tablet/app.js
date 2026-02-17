/**
 * Phase 10 - Interface Tablette Pepper
 * Application JavaScript pour l'interface tactile
 */

const CONFIG = {
    // URL du serveur WS: query param ?ws=... > host page > localhost
    serverUrl: (() => {
        let wsParam = '';
        try {
            wsParam = new URLSearchParams(window.location.search).get('ws') || '';
        } catch (e) {
            wsParam = '';
        }
        if (wsParam) return wsParam;

        const host = window.location.hostname || 'localhost';
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        return `${protocol}://${host}:8765`;
    })(),

    // Timeouts
    connectionTimeout: 5000,
    scanTimeout: 30000,

    // Debug
    debug: true
};

const AppState = {
    currentScreen: 'home',
    connected: false,
    ws: null,
    products: [],
    filteredProducts: [],
    currentProduct: null,
    top3Results: [],
    currentFilter: 'all'
};

const App = {
    /**
     * Initialisation de l'application
     */
    init() {
        this.log('Initialisation de l\'application...');

        // Charger les produits de démonstration
        this.loadDemoProducts();

        // Tenter la connexion WebSocket
        this.connectWebSocket();

        // Afficher l'écran d'accueil
        this.showScreen('home');

        this.log('Application initialisée');
    },

    /**
     * Affichage d'un écran
     */
    showScreen(screenId) {
        this.log(`Affichage écran: ${screenId}`);

        // Masquer tous les écrans
        document.querySelectorAll('.screen').forEach(screen => {
            screen.classList.remove('active');
        });

        // Afficher l'écran demandé
        const screen = document.getElementById(`screen-${screenId}`);
        if (screen) {
            screen.classList.add('active');
            AppState.currentScreen = screenId;
            if (screenId === 'barcode-scan') {
                this.updateBarcodeStatus('waiting', 'En attente du code-barres...');
            }
        }
    },

    /**
     * Affichage de l'écran de chargement
     */
    showLoading(message = 'Chargement...') {
        document.getElementById('loading-text').textContent = message;
        this.showScreen('loading');
    },

    /**
     * Démarrer le scan visuel
     */
    startVisualScan() {
        this.log('Démarrage scan visuel');
        this.showLoading('Analyse du produit en cours...');

        // Envoyer commande au serveur
        const sent = this.sendCommand('start_visual_scan');
        if (!sent) {
            this.showScreen('scan-choice');
            this.showError('Connexion tablette indisponible.');
            return;
        }

        // Timeout de sécurité
        setTimeout(() => {
            if (AppState.currentScreen === 'loading') {
                this.showScreen('scan-choice');
                this.showError('Le scan a pris trop de temps. Veuillez réessayer.');
            }
        }, CONFIG.scanTimeout);
    },

    /**
     * Démarrer le scan code-barres
     */
    startBarcodeScan() {
        this.log('Démarrage scan code-barres');
        this.showScreen('barcode-scan');
        this.updateBarcodeStatus('waiting', 'Recherche du code-barres...');

        const sent = this.sendCommand('start_barcode_scan');
        if (!sent) {
            this.showError('Connexion tablette indisponible.');
            return;
        }

        setTimeout(() => {
            if (AppState.currentScreen === 'barcode-scan') {
                this.updateBarcodeStatus('error', 'Le scan a pris trop de temps. Réessayez.');
            }
        }, CONFIG.scanTimeout);
    },

    /**
     * Démarrer une question vocale fallback
     */
    startVoiceQuestion() {
        this.log('Démarrage question vocale fallback');
        const sent = this.sendCommand('start_voice_question', { duration_s: 9 });
        if (!sent) {
            this.showError('Connexion tablette indisponible.');
            return;
        }
        this.showLoading('Parlez, Pepper vous écoute...');
    },

    /**
     * Afficher les résultats Top-3
     */
    showTop3(results) {
        this.log('Affichage Top-3', results);

        AppState.top3Results = results;
        const container = document.getElementById('top3-cards');
        container.innerHTML = '';

        results.forEach((result, index) => {
            const card = document.createElement('div');
            card.className = 'top3-card';
            card.onclick = () => this.selectTop3Product(index);

            card.innerHTML = `
                <div class="top3-card-number">${index + 1}</div>
                <img class="top3-card-image" src="${result.image || 'placeholder.png'}" alt="${result.name}">
                <p class="top3-card-name">${result.name}</p>
                <p class="top3-card-confidence">${Math.round(result.confidence * 100)}% de confiance</p>
            `;

            container.appendChild(card);
        });

        this.showScreen('top3');
    },

    /**
     * Sélectionner un produit du Top-3
     */
    selectTop3Product(index) {
        const result = AppState.top3Results[index];
        if (result) {
            this.log(`Produit sélectionné: ${result.name}`);
            this.sendCommand('confirm_product', { ean: result.ean, index: index });
            this.showLoading('Validation du produit...');
        }
    },

    /**
     * Afficher une fiche produit
     */
    showProduct(product) {
        this.log('Affichage produit', product);

        AppState.currentProduct = product;

        document.getElementById('product-image').src = product.image || 'placeholder.png';
        document.getElementById('product-name').textContent = product.name || 'Produit inconnu';
        document.getElementById('product-brand').textContent = product.brand || '';
        document.getElementById('product-price').textContent = product.price ? `${product.price.toFixed(2)} €` : 'Prix non disponible';
        document.getElementById('product-usage').textContent = product.usage || 'Pas d\'information disponible';
        document.getElementById('product-hair-type').textContent = product.hair_type || 'Tous types';

        this.showScreen('product');
    },

    /**
     * Filtrer les produits par type de cheveux
     */
    filterProducts(filter) {
        this.log(`Filtre: ${filter}`);
        AppState.currentFilter = filter;

        // Mettre à jour les boutons de filtre
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.filter === filter);
        });

        // Filtrer les produits
        if (filter === 'all') {
            AppState.filteredProducts = [...AppState.products];
        } else {
            AppState.filteredProducts = AppState.products.filter(p => {
                const hairType = (p.hair_type || '').toLowerCase();
                return hairType.includes(filter.toLowerCase());
            });
        }

        // Afficher les produits filtrés
        this.renderProductsGrid();
    },

    /**
     * Rendre la grille de produits
     */
    renderProductsGrid() {
        const container = document.getElementById('products-grid');
        container.innerHTML = '';

        AppState.filteredProducts.forEach(product => {
            const item = document.createElement('div');
            item.className = 'product-grid-item';
            item.onclick = () => this.showProduct(product);

            item.innerHTML = `
                <img src="${product.image || 'placeholder.png'}" alt="${product.name}">
                <p class="name">${product.name}</p>
                <p class="price">${product.price ? product.price.toFixed(2) + ' €' : ''}</p>
            `;

            container.appendChild(item);
        });
    },

    /**
     * Afficher un message de sécurité
     */
    showSecurityMessage(title, message) {
        this.log('Message sécurité', { title, message });

        document.getElementById('security-title').textContent = title;
        document.getElementById('security-message').textContent = message;
        this.showScreen('security');
    },

    /**
     * Afficher une erreur
     */
    showError(message) {
        this.showSecurityMessage('Erreur', message);
    },

    /**
     * Mettre à jour le statut du scan code-barres
     */
    updateBarcodeStatus(status, message) {
        const icon = document.getElementById('barcode-status-icon');
        const text = document.getElementById('barcode-status-text');

        icon.className = 'status-icon ' + status;

        switch (status) {
            case 'waiting':
                icon.textContent = '⏳';
                break;
            case 'success':
                icon.textContent = '✅';
                break;
            case 'error':
                icon.textContent = '❌';
                break;
        }

        text.textContent = message;
    },


    /**
     * Connexion WebSocket au serveur Mac
     */
    connectWebSocket() {
        this.log(`Connexion WebSocket à ${CONFIG.serverUrl}...`);

        try {
            AppState.ws = new WebSocket(CONFIG.serverUrl);

            AppState.ws.onopen = () => {
                this.log('WebSocket connecté');
                AppState.connected = true;
                this.updateConnectionStatus('Connecté');
            };

            AppState.ws.onclose = () => {
                this.log('WebSocket déconnecté');
                AppState.connected = false;
                this.updateConnectionStatus('Déconnecté');

                // Tentative de reconnexion après 5s
                setTimeout(() => this.connectWebSocket(), 5000);
            };

            AppState.ws.onerror = (error) => {
                this.log('Erreur WebSocket', error);
                this.updateConnectionStatus('Erreur');
            };

            AppState.ws.onmessage = (event) => {
                this.handleServerMessage(event.data);
            };

        } catch (error) {
            this.log('Erreur création WebSocket', error);
        }
    },

    /**
     * Envoyer une commande au serveur
     */
    sendCommand(command, data = {}) {
        if (!AppState.connected) {
            this.log('Non connecté, commande ignorée:', command);
            return false;
        }

        const message = JSON.stringify({
            type: 'command',
            command: command,
            data: data,
            timestamp: Date.now()
        });

        this.log('Envoi commande:', message);
        AppState.ws.send(message);
        return true;
    },

    /**
     * Traiter un message du serveur
     */
    handleServerMessage(rawMessage) {
        try {
            const message = JSON.parse(rawMessage);
            this.log('Message reçu:', message);

            switch (message.type) {
                case 'product_identified':
                    this.showProduct(message.product);
                    break;

                case 'top3_results':
                    this.showTop3(message.results);
                    break;

                case 'barcode_detected':
                    this.updateBarcodeStatus('success', `Code-barres détecté: ${message.ean}`);
                    if (message.product) {
                        setTimeout(() => this.showProduct(message.product), 1000);
                    }
                    break;

                case 'barcode_failed':
                    this.updateBarcodeStatus('error', 'Code-barres non reconnu');
                    break;

                case 'security_alert':
                    this.showSecurityMessage(message.title, message.message);
                    break;

                case 'error':
                    this.showError(message.message);
                    break;

                case 'show_screen':
                    this.showScreen(message.screen);
                    break;

                case 'products_list':
                    AppState.products = message.products;
                    this.filterProducts('all');
                    break;

                case 'status':
                    this.updateConnectionStatus(
                        message.status === 'connected'
                            ? 'Connecté'
                            : (message.status || 'Inconnu')
                    );
                    break;

                case 'qa_answer':
                    this.showSecurityMessage('Réponse Pepper', message.answer || 'Réponse vide');
                    break;

                default:
                    this.log('Message non géré:', message.type);
            }

        } catch (error) {
            this.log('Erreur parsing message:', error);
        }
    },

    /**
     * Mettre à jour le statut WebSocket affiché
     */
    updateConnectionStatus(statusText) {
        const statusEl = document.getElementById('ws-status');
        if (statusEl) {
            statusEl.textContent = `WebSocket: ${statusText}`;
        }
    },


    /**
     * Logger avec horodatage
     */
    log(...args) {
        if (CONFIG.debug) {
            console.log(`[${new Date().toISOString()}]`, ...args);
        }
    },

    /**
     * Charger des produits de démonstration
     */
    loadDemoProducts() {
        AppState.products = [
            {
                ean: '3282770149272',
                name: 'Shampooing Extra-Doux Lait d\'Avoine',
                brand: 'Klorane',
                price: 9.50,
                usage: 'Shampooing doux pour usage fréquent. Appliquer sur cheveux mouillés, masser et rincer.',
                hair_type: 'Tous types',
                image: 'https://via.placeholder.com/200x200?text=Klorane'
            },
            {
                ean: '3600523735501',
                name: 'Elseve Color-Vive Shampooing',
                brand: 'L\'Oréal Paris',
                price: 4.90,
                usage: 'Protection couleur pour cheveux colorés. Usage quotidien possible.',
                hair_type: 'Cheveux colorés',
                image: 'https://via.placeholder.com/200x200?text=Elseve'
            },
            {
                ean: '3600542154796',
                name: 'Ultra Doux Shampooing Miel',
                brand: 'Garnier',
                price: 3.80,
                usage: 'Shampooing nourrissant au miel. Répare et renforce les cheveux.',
                hair_type: 'Cheveux secs',
                image: 'https://via.placeholder.com/200x200?text=Garnier'
            },
            {
                ean: '3282779354424',
                name: 'Forticea Shampooing Énergisant',
                brand: 'René Furterer',
                price: 14.90,
                usage: 'Stimule la croissance des cheveux. Usage 2-3 fois par semaine.',
                hair_type: 'Cheveux fragilisés',
                image: 'https://via.placeholder.com/200x200?text=Furterer'
            },
            {
                ean: '3282770107357',
                name: 'Elution Shampooing Dermo-Protecteur',
                brand: 'Ducray',
                price: 11.90,
                usage: 'Rééquilibre le cuir chevelu. Convient aux cuirs chevelus sensibles.',
                hair_type: 'Cuir chevelu sensible',
                image: 'https://via.placeholder.com/200x200?text=Ducray'
            },
            {
                ean: '3401360262652',
                name: 'Nodé Shampooing Fluide',
                brand: 'Bioderma',
                price: 10.50,
                usage: 'Shampooing quotidien non détergent. Respecte l\'équilibre du cuir chevelu.',
                hair_type: 'Tous types',
                image: 'https://via.placeholder.com/200x200?text=Bioderma'
            },
            {
                ean: '3337871324568',
                name: 'Dercos Anti-Pelliculaire',
                brand: 'Vichy',
                price: 12.90,
                usage: 'Élimine les pellicules dès la première application. Usage 2-3 fois/semaine.',
                hair_type: 'Pellicules',
                image: 'https://via.placeholder.com/200x200?text=Vichy'
            },
            {
                ean: '3338221000125',
                name: 'Phytokératine Extrême Shampooing',
                brand: 'Phyto',
                price: 13.50,
                usage: 'Répare les cheveux très abîmés. Kératine végétale.',
                hair_type: 'Cheveux abîmés',
                image: 'https://via.placeholder.com/200x200?text=Phyto'
            },
            {
                ean: '3433422404847',
                name: 'Kerium Shampooing Anti-Chute',
                brand: 'La Roche-Posay',
                price: 15.90,
                usage: 'Réduit la chute de cheveux. Enrichi en Madécassoside.',
                hair_type: 'Chute de cheveux',
                image: 'https://via.placeholder.com/200x200?text=LRP'
            },
            {
                ean: '3264680003783',
                name: 'Rêve de Miel Shampooing',
                brand: 'Nuxe',
                price: 11.50,
                usage: 'Shampooing doux et nourrissant au miel. Pour cheveux normaux à secs.',
                hair_type: 'Cheveux normaux à secs',
                image: 'https://via.placeholder.com/200x200?text=Nuxe'
            }
        ];

        AppState.filteredProducts = [...AppState.products];
        this.log(`${AppState.products.length} produits chargés`);
    }
};

function bootstrapApp() {
    if (window.__PEPPER_APP_BOOTSTRAPPED__) {
        return;
    }
    window.__PEPPER_APP_BOOTSTRAPPED__ = true;
    App.init();
}

// Exposer l'application globalement pour les onclick HTML
window.App = App;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootstrapApp);
} else {
    bootstrapApp();
}
