document.addEventListener("DOMContentLoaded", function () {

    const input = document.getElementById("mensaje");
    const chat = document.getElementById("chat");
    const buscador = document.getElementById("buscadorCompanias");


    /* =========================================
       BUSCADOR DE COMPAÑÍAS
       ========================================= */

    if (buscador) {

        buscador.addEventListener("input", function () {

            const texto = this.value
                .toLowerCase()
                .trim();

            const companias =
                document.querySelectorAll(".company-item");


            companias.forEach(function (compania) {

                const nombre =
                    compania.dataset.company || "";

                if (nombre.includes(texto)) {

                    compania.style.display = "flex";

                } else {

                    compania.style.display = "none";

                }

            });

        });

    }



    /* =========================================
       ENTER PARA ENVIAR
       ========================================= */

    if (input) {

        input.addEventListener("keydown", function (event) {

            if (
                event.key === "Enter" &&
                !event.shiftKey
            ) {

                event.preventDefault();

                enviarMensaje();

            }

        });

    }



    /* =========================================
       F3 — BUSCADOR
       ========================================= */

    document.addEventListener("keydown", function (event) {

        if (event.key === "F3") {

            event.preventDefault();

            window.location.href = "/buscar";

        }

    });



    /* =========================================
       SCROLL AUTOMÁTICO
       ========================================= */

    window.scrollChatAbajo = function () {

        if (!chat) return;

        chat.scrollTop = chat.scrollHeight;

    };


    scrollChatAbajo();

});



/* =========================================
   SUGERENCIAS
   ========================================= */

function usarSugerencia(texto) {

    const input =
        document.getElementById("mensaje");

    if (!input) return;

    input.value = texto;

    input.focus();

}



/* =========================================
   ENVIAR MENSAJE
   ========================================= */

async function enviarMensaje() {

    const input =
        document.getElementById("mensaje");

    const chat =
        document.getElementById("chat");


    if (!input || !chat) return;


    const texto =
        input.value.trim();


    if (!texto) return;



    /* MENSAJE DEL USUARIO */

    const mensajeUsuario =
        document.createElement("div");

    mensajeUsuario.className =
        "chat-message user-message";


    mensajeUsuario.innerHTML = `

        <div class="message-content">

            ${escapeHtml(texto)}

        </div>

    `;


    chat.appendChild(mensajeUsuario);


    input.value = "";


    chat.scrollTop =
        chat.scrollHeight;



    /* INDICADOR */

    const pensando =
        document.createElement("div");

    pensando.className =
        "chat-message assistant-message thinking";


    pensando.innerHTML = `

        <div class="message-content">

            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>
            <span class="thinking-dot"></span>

        </div>

    `;


    chat.appendChild(pensando);


    chat.scrollTop =
        chat.scrollHeight;



    try {

        const respuesta =
            await fetch("/chat", {

                method: "POST",

                headers: {

                    "Content-Type":
                        "application/json"

                },

                body: JSON.stringify({

                    mensaje: texto

                })

            });


        const datos =
            await respuesta.json();


        pensando.remove();


        const mensajeIA =
            document.createElement("div");

        mensajeIA.className =
            "chat-message assistant-message";


        mensajeIA.innerHTML = `

            <div class="message-avatar">

                ✦

            </div>

            <div class="message-content">

                ${escapeHtml(
                    datos.respuesta ||
                    "No pude obtener una respuesta."
                )}

            </div>

        `;


        chat.appendChild(mensajeIA);


        chat.scrollTop =
            chat.scrollHeight;


    } catch (error) {

        pensando.remove();


        const errorMessage =
            document.createElement("div");

        errorMessage.className =
            "chat-message assistant-message";


        errorMessage.innerHTML = `

            <div class="message-avatar">

                !

            </div>

            <div class="message-content">

                No pude conectar con el asistente.

            </div>

        `;


        chat.appendChild(errorMessage);


        chat.scrollTop =
            chat.scrollHeight;

    }

}



/* =========================================
   SEGURIDAD HTML
   ========================================= */

function escapeHtml(texto) {

    const div =
        document.createElement("div");

    div.textContent =
        texto;

    return div.innerHTML;

}