// Botón «Más datos»: por defecto el servidor carga una muestra pequeña; desde aquí se pide más
// historia (POST api/ampliar). También pinta la pantalla de espera del primer arranque.
//   NodosAmpliar.montar(boton, { alActualizar, alEstado })  -> alActualizar() cuando el servidor publica
//   datos nuevos; alEstado(estado) en cada consulta del estado (cada 15 s mientras actualiza)
(() => {
  const estilos = `
  dialog.ampliar { border: 1px solid var(--line); border-radius: 12px; background: var(--surface); color: var(--ink);
    padding: 18px; width: min(420px, calc(100vw - 32px)); box-shadow: 0 12px 40px #0004; font: 14px/1.45 var(--font-body); }
  dialog.ampliar::backdrop { background: #0006; }
  dialog.ampliar h2 { font: 700 18px var(--font-display); margin: 0 0 6px; }
  dialog.ampliar p { margin: 0 0 12px; color: var(--muted); }
  dialog.ampliar p b { color: var(--ink); font-weight: 500; }
  dialog.ampliar .opciones { display: grid; gap: 8px; margin-bottom: 12px; }
  dialog.ampliar .opcion { display: flex; justify-content: space-between; align-items: center; gap: 12px; width: 100%;
    font: 500 14px var(--font-body); color: var(--ink); background: transparent; border: 1px solid var(--line);
    border-radius: 8px; padding: 10px 12px; cursor: pointer; text-align: left; }
  dialog.ampliar .opcion:hover:not(:disabled) { border-color: var(--accent); }
  dialog.ampliar .opcion:disabled { opacity: 0.5; cursor: default; }
  dialog.ampliar .opcion span { font: 12px var(--font-mono); color: var(--muted); }
  dialog.ampliar .msg { min-height: 1.4em; font-size: 13px; color: var(--ink); margin-bottom: 10px; }
  dialog.ampliar .pie { display: flex; justify-content: flex-end; }
  dialog.ampliar button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .espera { text-align: left; margin-top: 12px; display: grid; gap: 6px; }
  .espera .barra { height: 6px; border-radius: 3px; background: var(--line); overflow: hidden; }
  .espera .barra i { display: block; height: 100%; background: var(--accent); border-radius: 3px; transition: width .6s ease; }
  .espera .paso { color: var(--ink); font-weight: 500; }
  .espera .det { font: 12px var(--font-mono); color: var(--muted); }
  .espera details { margin-top: 6px; border-top: 1px solid var(--line); padding-top: 8px; }
  .espera summary { cursor: pointer; color: var(--ink); font-weight: 500; }
  .espera ul { margin: 6px 0 0; padding-left: 18px; color: var(--muted); font-size: 13px; display: grid; gap: 4px; }
  .espera .error { color: var(--bad, #B03F2B); }`;
  // Estilos al cargar el script: espera() puede usarse antes de montar el botón.
  const hoja = document.createElement('style'); hoja.textContent = estilos; document.head.appendChild(hoja);

  const NOMBRES = { 7: '1 semana', 14: '2 semanas', 30: '1 mes' };
  const duracion = (min) => min < 60 ? `~${min} min` : `~${(min / 60).toLocaleString('es-CL', { maximumFractionDigits: 1 })} h`;
  const fecha = (d) => new Date(d + 'T12:00').toLocaleDateString('es-CL', { day: 'numeric', month: 'short', year: 'numeric' });

  async function json(url, opciones) {
    const r = await fetch(url, { cache: 'no-cache', ...opciones });
    const datos = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(datos.detail || 'HTTP ' + r.status);
    return datos;
  }

  function montar(boton, { alActualizar, alEstado } = {}) {
    if (!boton) return;
    const dlg = document.createElement('dialog');
    dlg.className = 'ampliar';
    dlg.setAttribute('aria-labelledby', 'ampliar-t');
    dlg.innerHTML = `<h2 id="ampliar-t">Más historia</h2><p class="txt"></p><div class="opciones"></div>
      <div class="msg" role="status"></div><div class="pie"><button class="btn" value="cerrar">Cerrar</button></div>`;
    document.body.appendChild(dlg);
    dlg.querySelector('[value=cerrar]').addEventListener('click', () => dlg.close());
    dlg.addEventListener('click', (e) => { if (e.target === dlg) dlg.close(); });

    let estado = null, version;
    boton.hidden = true;

    async function pintar() {
      const dias = await json('api/dias').catch(() => ({ demanda: [] }));
      const dem = dias.demanda || [];
      const pedido = estado?.ventana?.['demanda-real'] || 0;
      dlg.querySelector('.txt').innerHTML = dem.length
        ? `Ahora hay <b>${dem.length} ${dem.length === 1 ? 'día' : 'días'}</b> de demanda real (${dem.length > 1 ? fecha(dem[0].dia) + ' – ' : ''}${fecha(dem.at(-1).dia)}). ` +
          'Para ver más, el servidor descarga días anteriores del Coordinador. El mapa sigue funcionando mientras tanto y se actualiza solo al terminar.'
        : 'Todavía no hay demanda real cargada. Puedes pedir más historia y se descargará en la próxima actualización.';
      const caja = dlg.querySelector('.opciones');
      caja.innerHTML = '';
      for (const o of estado?.ampliar?.opciones || []) {
        const b = document.createElement('button');
        b.className = 'opcion';
        b.disabled = pedido >= o.dias;
        b.innerHTML = `<b></b><span></span>`;
        b.querySelector('b').textContent = NOMBRES[o.dias] || `${o.dias} días`;
        b.querySelector('span').textContent = pedido >= o.dias ? 'ya pedido' : duracion(o.minutos);
        b.addEventListener('click', () => pedir(o.dias));
        caja.appendChild(b);
      }
      dlg.querySelector('.msg').textContent = estado?.en_curso
        ? `Actualizando ahora${estado.paso ? ': ' + estado.paso : ''}…` : '';
    }

    async function pedir(dias) {
      const msg = dlg.querySelector('.msg');
      dlg.querySelectorAll('.opcion').forEach(b => b.disabled = true);
      msg.textContent = 'Pidiendo…';
      try {
        const r = await json('api/ampliar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ dias }) });
        estado = { ...estado, ventana: r.ventana, en_curso: true };
        await pintar();
        msg.textContent = r.en_curso
          ? 'Pedido. Empieza cuando termine la actualización en curso; el mapa se actualizará solo.'
          : 'Pedido. La descarga empezó; el mapa se actualizará solo cuando termine.';
        vigilar(15000);
      } catch (e) {
        msg.textContent = 'No se pudo: ' + e.message;
        await pintar();
      }
    }

    boton.addEventListener('click', async () => { await pintar(); dlg.showModal(); });

    let reloj = null;
    async function vigilar(espera) {
      clearTimeout(reloj);
      if (espera) { reloj = setTimeout(vigilar, espera); return; }
      try {
        estado = await json('api/estado');
        boton.hidden = !estado.ampliar?.permitido;
        alEstado?.(estado);
        if (version !== undefined && estado.ultima_actualizacion !== version) alActualizar?.();
        version = estado.ultima_actualizacion;
        if (dlg.open) await pintar();
      } catch (e) { /* sin servidor (p. ej. exportación estática): el botón queda oculto */ }
      reloj = setTimeout(vigilar, estado?.en_curso ? 15000 : 120000);
    }
    vigilar();
  }

  // Pantalla de espera mientras no hay datos: avance de la actualización y por qué tarda.
  const LIMITES = [
    'La API pública del Coordinador entrega como máximo <b>10.000 filas por consulta</b> y tarda unos <b>4–5 s</b> en responder cada una.',
    'Un día de demanda real son <b>~400.000 registros</b> (≈41 consultas) y uno de costo marginal ~160.000 (un precio cada 15 min en ~1.650 barras).',
    'Para no saturar la API se esperan 2 s entre consultas; si responde 429 o 502 se reintenta con pausas.',
    'La demanda real se publica <b>por mes completo, con 1–2 meses de desfase</b>, y el costo marginal con ~1 semana: por eso los días del mapa no son de hoy.',
    'Por eso se parte con una <b>muestra de 1 día</b>. Cuando aparezca el mapa, «Más datos» descarga más historia.',
  ];
  function espera(el, e) {
    if (!el) return;
    e = e || {};
    const min = e.transcurrido_s != null ? Math.floor(e.transcurrido_s / 60) : null;
    const avance = e.pasos_total ? Math.max(0.03, (e.paso_n - 1) / e.pasos_total) : 0.03;
    const partes = [];
    if (e.en_curso) {
      partes.push(`<div class="barra" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(avance * 100)}"><i style="width:${(avance * 100).toFixed(0)}%"></i></div>`);
      partes.push(`<div class="paso"></div>`);
      partes.push(`<div class="det"></div>`);
    } else if (e.error) {
      partes.push(`<div class="paso error"></div>`);
    }
    partes.push(`<details open><summary>¿Por qué tarda?</summary><ul>${LIMITES.map(t => `<li>${t}</li>`).join('')}</ul></details>`);
    el.innerHTML = `<div class="espera">${partes.join('')}</div>`;
    const paso = el.querySelector('.paso'), det = el.querySelector('.det');
    if (e.en_curso) {
      paso.textContent = (e.pasos_total ? `Paso ${e.paso_n} de ${e.pasos_total} · ` : '') + (e.paso || 'empezando');
      det.textContent = [e.detalle, min != null ? `${min} min` : null].filter(Boolean).join(' · ');
    } else if (e.error) {
      paso.textContent = 'La actualización falló y se reintentará: ' + String(e.error).split(/\r?\n/)[0];
    }
  }

  window.NodosAmpliar = { montar, espera };
})();
