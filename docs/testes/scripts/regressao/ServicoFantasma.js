/**
 * Amostra de regressão da varredura `rota_orfa`.
 *
 * As três chamadas abaixo apontam para caminhos que não existem na API. Cada
 * uma reproduz uma cegueira real, vivida durante a construção da varredura em
 * 02/09/2026, quando a sondagem inicial era um `grep` de uma linha:
 *
 * 1. chamada simples — o caso que qualquer regex pega;
 * 2. chamada quebrada entre o parêntese e a crase — invisível para `grep`, que
 *    não atravessa `\n`, e é exatamente como o `desfazerDecisaoDeRecomendacao`
 *    está escrito no serviço de influenciadores. Quem cobre este caso é o
 *    `\s*` do padrão, não o `re.S`;
 * 3. `api.raw`, o buscador de binário com Authorization — ficar de fora da
 *    lista de métodos fazia `/reports/{id}/download` parecer rota órfã.
 *
 * Se algum destes deixar de aparecer nos achados, uma regra ficou larga demais.
 */
import { api } from '../lib/api.js'

export async function chamadaSimples() {
  const res = await api.get('/influencers/inexistente')
  return res.data
}

export async function chamadaMultilinha(id) {
  await api.delete(
    `/campaigns/${id}/inexistente?analysis_id=abc`
  )
}

export async function chamadaBinaria(id) {
  const resp = await api.raw(`/reports/${id}/inexistente`)
  return resp.blob()
}
