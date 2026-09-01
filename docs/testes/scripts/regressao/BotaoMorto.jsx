/**
 * Amostra de regressão da varredura de botão morto — não é código do produto.
 *
 * O botão abaixo não tem `onClick`, `type="submit"`, `href`, `to` nem
 * `disabled`, e não está dentro de um link. É a forma exata dos 7 botões mortos
 * que a bateria achou em 27/08, entre eles "Gerar Relatório" e "Abrir auditoria".
 */
export default function BotaoMorto() {
  return (
    <div>
      <Button variant="primary" leftIcon={Download}>
        Exportar
      </Button>
    </div>
  )
}
