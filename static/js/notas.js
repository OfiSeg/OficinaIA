// ==========================================
// BLOC DE NOTAS
// ==========================================


let notas = JSON.parse(

    localStorage.getItem(
        "oficina_notas"
    ) || "[]"

);


// ==========================================
// GUARDAR
// ==========================================

function guardarNotas() {

    localStorage.setItem(

        "oficina_notas",

        JSON.stringify(notas)

    );

}


// ==========================================
// MOSTRAR
// ==========================================

function mostrarNotas() {

    const lista =
        document.getElementById(
            "listaNotas"
        );


    lista.innerHTML = "";


    notas.forEach(

        function(nota, indice) {


            const elemento =
                document.createElement(
                    "div"
                );


            elemento.className =
                "nota";


            elemento.innerHTML = `

                <div class="nota-texto">

                    <input
                        type="checkbox"
                        ${nota.completada ? "checked" : ""}
                        onchange="completarNota(${indice})"
                    >

                    <span
                        class="${nota.completada ? "completada" : ""}"
                    >

                        ${nota.texto}

                    </span>

                </div>


                <button
                    onclick="eliminarNota(${indice})"
                    class="nota-eliminar"
                >

                    🗑️

                </button>

            `;


            lista.appendChild(
                elemento
            );


        }

    );

}


// ==========================================
// AGREGAR
// ==========================================

function agregarNota() {

    const campo =
        document.getElementById(
            "nuevaNota"
        );


    const texto =
        campo.value.trim();


    if (!texto) {

        return;

    }


    notas.push({

        texto: texto,

        completada: false

    });


    campo.value = "";


    guardarNotas();

    mostrarNotas();

}


// ==========================================
// COMPLETAR
// ==========================================

function completarNota(indice) {

    notas[indice].completada =
        !notas[indice].completada;


    guardarNotas();

    mostrarNotas();

}


// ==========================================
// ELIMINAR
// ==========================================

function eliminarNota(indice) {

    notas.splice(

        indice,

        1

    );


    guardarNotas();

    mostrarNotas();

}


// ==========================================
// ENTER PARA AGREGAR
// ==========================================

const campoNota =
    document.getElementById(
        "nuevaNota"
    );


if (campoNota) {

    campoNota.addEventListener(

        "keydown",

        function(event) {

            if (
                event.key === "Enter"
            ) {

                agregarNota();

            }

        }

    );

}


// ==========================================
// INICIAR
// ==========================================

mostrarNotas();