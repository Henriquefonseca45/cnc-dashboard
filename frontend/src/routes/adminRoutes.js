const BASE_URL = "http://192.168.17.39:8000";

export const adminRoutes = [
  {
    grupo: "Produção",
    itens: [
      {
        nome: "Painel de Produção",
        rota: `${BASE_URL}/visual?readonly=1`,
        descricao: "Painel visual de produção em modo somente leitura.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: true,
      },
      {
        nome: "Facilitador",
        rota: `${BASE_URL}/facilitador`,
        descricao: "Tela do facilitador para acompanhamento e apoio da produção.",
        perfis: ["admin", "facilitador", "supervisor"],
        ativo: true,
      },
      {
        nome: "Programador",
        rota: `${BASE_URL}/programador`,
        descricao: "Tela de programação, filas, históricos e controles CNC.",
        perfis: ["admin", "programador", "supervisor"],
        ativo: true,
      },
    ],
  },
  {
    grupo: "Operador",
    itens: [
      {
        nome: "Operador CNC01",
        rota: `${BASE_URL}/operador/CNC01`,
        descricao: "Painel do operador da CNC01.",
        perfis: ["admin", "operador", "supervisor"],
        ativo: true,
      },
    ],
  },
  {
    grupo: "Almoxarifado",
    itens: [
      {
        nome: "Almoxarifado",
        rota: `${BASE_URL}/almoxarifado`,
        descricao: "Central do almoxarifado com cards e solicitações de material.",
        perfis: ["admin", "almoxarifado", "supervisor"],
        ativo: true,
      },
    ],
  },
  {
    grupo: "Administração",
    itens: [
      {
        nome: "Apontamentos de Status",
        rota: `${BASE_URL}/admin/status-apontamentos`,
        descricao: "Administração e invalidação de apontamentos de status.",
        perfis: ["admin", "supervisor"],
        ativo: true,
      },
    ],
  },
];
