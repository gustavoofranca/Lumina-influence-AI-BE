/**
 * Amostra de regressão da varredura de i18n — não é código do produto.
 *
 * Cada linha abaixo é um defeito **real** que passou por duas auditorias de
 * idioma porque a varredura não olhava para aquele formato. Rodar o script
 * contra esta pasta precisa acusar os dois:
 *
 *   python3 docs/testes/scripts/texto_fora_do_i18n.py docs/testes/scripts/regressao
 *
 * Se algum dia sair "0 literal(is)", a varredura regrediu.
 */
export default function PontosCegos({ inf, setToast }) {
  return (
    <div>
      {/* Alvo 3: texto colado a uma expressão — o alvo original exige um
          sinal de maior antes do texto e não enxerga este caso. */}
      <span>{formatFollowers(inf.followers)} seguidores</span>

      {/* Alvo 4: string de interface dentro de handler. Não está entre tags
          nem em atributo. */}
      <button onClick={() => setToast({ message: 'Download iniciado' })}>
        {t('influenciador.acoes.baixar')}
      </button>
    </div>
  )
}
