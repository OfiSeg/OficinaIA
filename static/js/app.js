// ==========================================================
// OFICINA SEGUROS
// JAVASCRIPT PRINCIPAL
// ==========================================================


// ==========================================================
// BUSCADOR DE COMPAÑÍAS
// ==========================================================

const buscadorCompanias =
    document.getElementById(
        "buscadorCompanias"
    );


const listaCompanias =
    document.getElementById(
        "listaCompanias"
    );


if (
    buscadorCompanias &&
    listaCompanias
) {


    buscadorCompanias.addEventListener(
        "input",
        function() {


            const texto =
                this.value
                    .toLowerCase()
                    .trim();


            const companias =
                listaCompanias.querySelectorAll(
                    ".company-item"
                );


            companias.forEach(
                compania => {


                    const nombre =
                        compania.dataset.company ||
                        "";


                    if (
                        nombre.includes(
                            texto
                        )
                    ) {

                        compania.style.display =
                            "flex";

                    } else {

                        compania.style.display =
                            "none";

                    }

                }
            );

        }
    );

}


// ==========================================================
// CHAT
// ==========================================================

const mensaje =
    document.getElementById(
        "mensaje"
    );


const chat =
    document.getElementById(
        "chat"
    );


// ==========================================================
// ENVIAR MENSAJE
// ==========================================================

async function enviarMensaje() {


    if (!mensaje || !chat) {

        return;

    }


    const texto =
        mensaje.value.trim();


    if (!texto) {

        return;

    }


    // ------------------------------------------------------
    // ELIMINAR BIENVENIDA
    // ------------------------------------------------------

    const bienvenida =
        chat.querySelector(
            ".welcome"
        );


    if (bienvenida) {

        bienvenida.remove();

    }


    // ------------------------------------------------------
    // MENSAJE USUARIO
    // ------------------------------------------------------

    agregarMensaje(
        texto,
        true
    );


    mensaje.value = "";


    // ------------------------------------------------------
    // SCROLL ABAJO
    // ------------------------------------------------------

    bajarChat();


    // ------------------------------------------------------
    // INDICADOR
    // ------------------------------------------------------

    const escribiendo =
        document.createElement(
            "div"
        );


    escribiendo.className =
        "chat-message";


    escribiendo.id =
        "mensajeEscribiendo";


    escribiendo.innerHTML = `

        <div class="message-icon">

            ✦

        </div>

        <div class="message-content">

            <p>

                Escribiendo...

            </p>

        </div>

    `;


    chat.appendChild(
        escribiendo
    );


    bajarChat();


    try {


        const response =
            await fetch(
                "/api/chat",
                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            mensaje:
                                texto

                        })

                }
            );


        const data =
            await response.json();


        const indicador =
            document.getElementById(
                "mensajeEscribiendo"
            );


        if (indicador) {

            indicador.remove();

        }


        agregarMensaje(
            data.respuesta ||
            "No pude procesar la consulta.",
            false
        );


        bajarChat();


    } catch (error) {


        const indicador =
            document.getElementById(
                "mensajeEscribiendo"
            );


        if (indicador) {

            indicador.remove();

        }


        agregarMensaje(
            "No pude conectarme con el servidor.",
            false
        );


        bajarChat();

    }

}


// ==========================================================
// AGREGAR MENSAJE
// ==========================================================

function agregarMensaje(
    texto,
    usuario
) {


    if (!chat) {

        return;

    }


    const div =
        document.createElement(
            "div"
        );


    div.className =
        usuario
            ? "chat-message user"
            : "chat-message";


    div.innerHTML = `

        ${
            usuario
                ? ""
                : `
                    <div class="message-icon">
                        ✦
                    </div>
                `
        }

        <div class="message-content">

            <strong>

                ${
                    usuario
                        ? "Vos"
                        : "Asistente"
                }

            </strong>

            <p>

                ${escaparHTML(texto)}

            </p>

        </div>

    `;


    chat.appendChild(
        div
    );

}


// ==========================================================
// ESCAPAR HTML
// ==========================================================

function escaparHTML(
    texto
) {


    const div =
        document.createElement(
            "div"
        );


    div.textContent =
        texto;


    return div.innerHTML;

}


// ==========================================================
// SCROLL AUTOMÁTICO
// ==========================================================

function bajarChat() {


    if (!chat) {

        return;

    }


    setTimeout(
        () => {

            chat.scrollTo({

                top:
                    chat.scrollHeight,

                behavior:
                    "smooth"

            });

        },
        50
    );

}


// ==========================================================
// SUGERENCIAS
// ==========================================================

function usarSugerencia(
    texto
) {


    if (!mensaje) {

        return;

    }


    mensaje.value =
        texto;


    mensaje.focus();

}


// ==========================================================
// ENTER PARA ENVIAR
// ==========================================================

if (mensaje) {


    mensaje.addEventListener(
        "keydown",
        function(event) {


            if (
                event.key ===
                "Enter"
            ) {


                event.preventDefault();


                enviarMensaje();

            }

        }
    );

}


// ==========================================================
// F3
// ==========================================================

document.addEventListener(
    "keydown",
    function(event) {


        if (
            event.key === "F3"
        ) {


            event.preventDefault();


            window.location.href =
                "/buscar";

        }

    }
);