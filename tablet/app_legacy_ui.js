/**
 * Compat UI pour WebView Pepper ancienne (ES5).
 * Même écrans que index.html, sans syntaxe JS moderne.
 */
(function () {
    "use strict";

    function getWsFromQuery() {
        var search = window.location.search || "";
        var match = search.match(/[?&]ws=([^&]+)/);
        if (match && match[1]) {
            try {
                return decodeURIComponent(match[1]);
            } catch (e) {
                return match[1];
            }
        }
        return "";
    }

    var CONFIG = {
        serverUrl: (function () {
            var fromQuery = getWsFromQuery();
            if (fromQuery) {
                return fromQuery;
            }
            var host = window.location.hostname || "localhost";
            return "ws://" + host + ":8765";
        })(),
        scanTimeout: 30000,
        debug: true
    };

    var AppState = {
        currentScreen: "home",
        connected: false,
        ws: null,
        products: [],
        filteredProducts: [],
        top3Results: []
    };

    function byId(id) {
        return document.getElementById(id);
    }

    var App = {
        init: function () {
            this.loadDemoProducts();
            this.connectWebSocket();
            this.showScreen("home");
            this.log("UI compat initialisée");
        },

        log: function () {
            if (!CONFIG.debug || !window.console) {
                return;
            }
            var args = Array.prototype.slice.call(arguments);
            args.unshift("[" + new Date().toISOString() + "]");
            console.log.apply(console, args);
        },

        updateConnectionStatus: function (statusText) {
            var statusEl = byId("ws-status");
            if (statusEl) {
                statusEl.textContent = "WebSocket: " + statusText;
            }
        },

        showScreen: function (screenId) {
            var screens = document.getElementsByClassName("screen");
            var i = 0;
            for (i = 0; i < screens.length; i += 1) {
                screens[i].className = screens[i].className.replace(" active", "");
            }

            var screen = byId("screen-" + screenId);
            if (screen) {
                if (screen.className.indexOf("active") < 0) {
                    screen.className += " active";
                }
                AppState.currentScreen = screenId;
                if (screenId === "barcode-scan") {
                    this.updateBarcodeStatus("waiting", "En attente du code-barres...");
                }
            }
        },

        showLoading: function (message) {
            byId("loading-text").textContent = message || "Chargement...";
            this.showScreen("loading");
        },

        showSecurityMessage: function (title, message) {
            byId("security-title").textContent = title || "Information";
            byId("security-message").textContent = message || "";
            this.showScreen("security");
        },

        showError: function (message) {
            this.showSecurityMessage("Erreur", message || "Erreur inconnue");
        },

        updateBarcodeStatus: function (status, message) {
            var icon = byId("barcode-status-icon");
            var text = byId("barcode-status-text");
            if (!icon || !text) {
                return;
            }

            icon.className = "status-icon " + status;
            if (status === "success") {
                icon.textContent = "✅";
            } else if (status === "error") {
                icon.textContent = "❌";
            } else {
                icon.textContent = "⏳";
            }
            text.textContent = message || "";
        },

        sendCommand: function (command, data) {
            if (!AppState.connected || !AppState.ws || AppState.ws.readyState !== 1) {
                this.log("Commande ignorée (WS non connectée):", command);
                return false;
            }
            AppState.ws.send(JSON.stringify({
                type: "command",
                command: command,
                data: data || {},
                timestamp: Date.now()
            }));
            return true;
        },

        startVisualScan: function () {
            this.showLoading("Analyse du produit en cours...");
            if (!this.sendCommand("start_visual_scan", {})) {
                this.showError("Connexion tablette indisponible.");
                return;
            }

            var self = this;
            setTimeout(function () {
                if (AppState.currentScreen === "loading") {
                    self.showScreen("scan-choice");
                    self.showError("Le scan a pris trop de temps. Veuillez réessayer.");
                }
            }, CONFIG.scanTimeout);
        },

        startBarcodeScan: function () {
            this.showScreen("barcode-scan");
            this.updateBarcodeStatus("waiting", "Recherche du code-barres...");
            if (!this.sendCommand("start_barcode_scan", {})) {
                this.showError("Connexion tablette indisponible.");
                return;
            }

            var self = this;
            setTimeout(function () {
                if (AppState.currentScreen === "barcode-scan") {
                    self.updateBarcodeStatus("error", "Le scan a pris trop de temps. Réessayez.");
                }
            }, CONFIG.scanTimeout);
        },

        startVoiceQuestion: function () {
            if (!this.sendCommand("start_voice_question", { duration_s: 9 })) {
                this.showError("Connexion tablette indisponible.");
                return;
            }
            this.showLoading("Parlez, Pepper vous écoute...");
        },

        showProduct: function (product) {
            product = product || {};
            var img = byId("product-image");
            if (img) {
                img.src = product.image || "placeholder.png";
            }
            byId("product-name").textContent = product.name || "Produit inconnu";
            byId("product-brand").textContent = product.brand || "";
            byId("product-price").textContent = (typeof product.price === "number" && product.price > 0)
                ? (product.price.toFixed(2) + " €")
                : "Prix non disponible";
            byId("product-usage").textContent = product.usage || "Pas d'information disponible";
            byId("product-hair-type").textContent = product.hair_type || "Tous types";
            this.showScreen("product");
        },

        showTop3: function (results) {
            AppState.top3Results = results || [];
            var container = byId("top3-cards");
            container.innerHTML = "";
            var self = this;
            var i = 0;

            for (i = 0; i < AppState.top3Results.length; i += 1) {
                (function (idx) {
                    var result = AppState.top3Results[idx];
                    var card = document.createElement("div");
                    card.className = "top3-card";
                    card.onclick = function () {
                        self.selectTop3Product(idx);
                    };

                    var num = document.createElement("div");
                    num.className = "top3-card-number";
                    num.textContent = String(idx + 1);

                    var image = document.createElement("img");
                    image.className = "top3-card-image";
                    image.src = result.image || "placeholder.png";
                    image.alt = result.name || "Produit";

                    var name = document.createElement("p");
                    name.className = "top3-card-name";
                    name.textContent = result.name || "Produit";

                    var conf = document.createElement("p");
                    conf.className = "top3-card-confidence";
                    conf.textContent = String(Math.round((result.confidence || 0) * 100)) + "% de confiance";

                    card.appendChild(num);
                    card.appendChild(image);
                    card.appendChild(name);
                    card.appendChild(conf);
                    container.appendChild(card);
                })(i);
            }

            this.showScreen("top3");
        },

        selectTop3Product: function (index) {
            var result = AppState.top3Results[index];
            if (!result) {
                return;
            }
            this.sendCommand("confirm_product", { ean: result.ean, index: index });
            this.showLoading("Validation du produit...");
        },

        filterProducts: function (filter) {
            var buttons = document.getElementsByClassName("filter-btn");
            var i = 0;
            for (i = 0; i < buttons.length; i += 1) {
                if ((buttons[i].getAttribute("data-filter") || "") === filter) {
                    if (buttons[i].className.indexOf("active") < 0) {
                        buttons[i].className += " active";
                    }
                } else {
                    buttons[i].className = buttons[i].className.replace(" active", "");
                }
            }

            if (filter === "all") {
                AppState.filteredProducts = AppState.products.slice(0);
            } else {
                AppState.filteredProducts = [];
                for (i = 0; i < AppState.products.length; i += 1) {
                    var p = AppState.products[i];
                    var hairType = (p.hair_type || "").toLowerCase();
                    if (hairType.indexOf(String(filter).toLowerCase()) >= 0) {
                        AppState.filteredProducts.push(p);
                    }
                }
            }
            this.renderProductsGrid();
        },

        renderProductsGrid: function () {
            var container = byId("products-grid");
            container.innerHTML = "";
            var self = this;
            var i = 0;
            for (i = 0; i < AppState.filteredProducts.length; i += 1) {
                (function (idx) {
                    var product = AppState.filteredProducts[idx];
                    var item = document.createElement("div");
                    item.className = "product-grid-item";
                    item.onclick = function () {
                        self.showProduct(product);
                    };

                    var img = document.createElement("img");
                    img.src = product.image || "placeholder.png";
                    img.alt = product.name || "Produit";

                    var name = document.createElement("p");
                    name.className = "name";
                    name.textContent = product.name || "Produit";

                    var price = document.createElement("p");
                    price.className = "price";
                    price.textContent = (typeof product.price === "number")
                        ? (product.price.toFixed(2) + " €")
                        : "";

                    item.appendChild(img);
                    item.appendChild(name);
                    item.appendChild(price);
                    container.appendChild(item);
                })(i);
            }
        },

        handleServerMessage: function (rawMessage) {
            var message;
            try {
                message = JSON.parse(rawMessage);
            } catch (e) {
                this.log("Message invalide:", rawMessage);
                return;
            }

            if (message.type === "product_identified") {
                this.showProduct(message.product);
            } else if (message.type === "top3_results") {
                this.showTop3(message.results);
            } else if (message.type === "barcode_detected") {
                this.updateBarcodeStatus("success", "Code-barres détecté: " + (message.ean || ""));
                if (message.product) {
                    this.showProduct(message.product);
                }
            } else if (message.type === "barcode_failed") {
                this.updateBarcodeStatus("error", "Code-barres non reconnu");
            } else if (message.type === "security_alert") {
                this.showSecurityMessage(message.title || "Information", message.message || "");
            } else if (message.type === "error") {
                this.showError(message.message || "Erreur inconnue");
            } else if (message.type === "show_screen") {
                this.showScreen(message.screen || "home");
            } else if (message.type === "products_list") {
                AppState.products = message.products || [];
                this.filterProducts("all");
            } else if (message.type === "status") {
                this.updateConnectionStatus(message.status || "connecté");
            } else if (message.type === "qa_answer") {
                this.showSecurityMessage("Réponse Pepper", message.answer || "Réponse vide");
            }
        },

        connectWebSocket: function () {
            var self = this;
            try {
                AppState.ws = new WebSocket(CONFIG.serverUrl);
            } catch (e) {
                self.updateConnectionStatus("Erreur");
                setTimeout(function () { self.connectWebSocket(); }, 3000);
                return;
            }

            AppState.ws.onopen = function () {
                AppState.connected = true;
                self.updateConnectionStatus("Connecté");
            };

            AppState.ws.onclose = function () {
                AppState.connected = false;
                self.updateConnectionStatus("Déconnecté");
                setTimeout(function () { self.connectWebSocket(); }, 3000);
            };

            AppState.ws.onerror = function () {
                self.updateConnectionStatus("Erreur");
            };

            AppState.ws.onmessage = function (event) {
                self.handleServerMessage(event.data);
            };
        },

        loadDemoProducts: function () {
            AppState.products = [
                {
                    ean: "3282770149272",
                    name: "Shampooing Extra-Doux Lait d'Avoine",
                    brand: "Klorane",
                    price: 9.5,
                    usage: "Shampooing doux pour usage fréquent.",
                    hair_type: "Tous types",
                    image: "https://via.placeholder.com/200x200?text=Klorane"
                },
                {
                    ean: "3600523735501",
                    name: "Elseve Color-Vive Shampooing",
                    brand: "L'Oréal Paris",
                    price: 4.9,
                    usage: "Protection couleur pour cheveux colorés.",
                    hair_type: "Cheveux colorés",
                    image: "https://via.placeholder.com/200x200?text=Elseve"
                },
                {
                    ean: "3337871324568",
                    name: "Dercos Anti-Pelliculaire",
                    brand: "Vichy",
                    price: 12.9,
                    usage: "Élimine les pellicules.",
                    hair_type: "Pellicules",
                    image: "https://via.placeholder.com/200x200?text=Vichy"
                }
            ];
            AppState.filteredProducts = AppState.products.slice(0);
        }
    };

    function bootstrapApp() {
        if (window.__PEPPER_APP_BOOTSTRAPPED__) {
            return;
        }
        window.__PEPPER_APP_BOOTSTRAPPED__ = true;
        App.init();
    }

    window.App = App;
    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bootstrapApp);
    } else {
        bootstrapApp();
    }
})();
