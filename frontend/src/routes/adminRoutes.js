export const adminRoutes = [
  {
    grupo: "Produção",
    itens: [
      {
        nome: "Painel de Produção",
        rota: "/visual",
        descricao: "Visão visual da produção CNC.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: true,
      },
      {
        nome: "Programador",
        rota: "/programador",
        descricao: "Fila, upload, histórico e controle do programador.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: true,
      },
      {
        nome: "Operador",
        rota: "/operador",
        descricao: "Painel padrão do operador CNC.",
        perfis: ["admin", "operador", "supervisor"],
        ativo: true,
      },
      {
        nome: "Painel Produção",
        rota: "/painel-producao",
        descricao: "Atalho reservado para painel de produção dedicado.",
        perfis: ["admin", "gestao"],
        ativo: false,
      },
      {
        nome: "Produção",
        rota: "/producao",
        descricao: "Atalho reservado para rota de produção.",
        perfis: ["admin", "gestao"],
        ativo: false,
      },
    ],
  },
  {
    grupo: "Operador",
    itens: [
      {
        nome: "Operador CNC01",
        rota: "/operador/CNC01",
        descricao: "Painel direto da CNC01.",
        perfis: ["admin", "operador", "supervisor"],
        ativo: true,
      },
      {
        nome: "Operador CNC07",
        rota: "/operador/CNC07",
        descricao: "Painel direto da CNC07.",
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
        rota: "/almoxarifado",
        descricao: "Cards e chat de solicitações de material.",
        perfis: ["admin", "almoxarifado", "supervisor"],
        ativo: true,
      },
      {
        nome: "Almoxarifado TV",
        rota: "/almoxarifado-tv",
        descricao: "Painel de material somente leitura para TV.",
        perfis: ["admin", "almoxarifado", "supervisor"],
        ativo: true,
      },
      {
        nome: "Chat Almoxarifado",
        rota: "/almoxarifado-chat",
        descricao: "Atendimento das solicitações de material.",
        perfis: ["admin", "almoxarifado", "supervisor"],
        ativo: true,
      },
    ],
  },
  {
    grupo: "Dashboards",
    itens: [
      {
        nome: "Dashboard Principal",
        rota: "/visual",
        descricao: "Dashboard dentro do painel visual.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: true,
      },
      {
        nome: "DashManut",
        rota: "/visual",
        descricao: "Dashboard de manutenção dentro do painel visual.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: true,
      },
      {
        nome: "Dashboard",
        rota: "/dashboard",
        descricao: "Rota reservada para dashboard dedicado.",
        perfis: ["admin", "gestao"],
        ativo: false,
      },
    ],
  },
  {
    grupo: "Manutenção",
    itens: [
      {
        nome: "DashManut",
        rota: "/visual",
        descricao: "Indicadores de manutenção por CNC.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: true,
      },
    ],
  },
  {
    grupo: "Administração",
    itens: [
      {
        nome: "Central Admin",
        rota: "/admin/rotas",
        descricao: "Mapa do sistema com atalhos principais.",
        perfis: ["admin"],
        ativo: true,
      },
      {
        nome: "Apontamentos de Status",
        rota: "/admin/status-apontamentos",
        descricao: "Revisão e invalidação de apontamentos de status.",
        perfis: ["admin", "supervisor"],
        ativo: true,
      },
      {
        nome: "Admin",
        rota: "/admin",
        descricao: "Área administrativa geral.",
        perfis: ["admin"],
        ativo: false,
      },
      {
        nome: "Usuários",
        rota: "/admin/usuarios",
        descricao: "Cadastro e permissões de usuários.",
        perfis: ["admin"],
        ativo: false,
      },
      {
        nome: "Máquinas",
        rota: "/admin/maquinas",
        descricao: "Configuração de máquinas CNC.",
        perfis: ["admin"],
        ativo: false,
      },
      {
        nome: "Configurações",
        rota: "/admin/configuracoes",
        descricao: "Configurações gerais do sistema.",
        perfis: ["admin"],
        ativo: false,
      },
    ],
  },
  {
    grupo: "Históricos",
    itens: [
      {
        nome: "Histórico de Status",
        rota: "/historico-status",
        descricao: "Histórico dedicado de status das CNCs.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: false,
      },
      {
        nome: "Histórico de Material",
        rota: "/historico-material",
        descricao: "Histórico dedicado de solicitações de material.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: false,
      },
      {
        nome: "Histórico de Produção",
        rota: "/historico-producao",
        descricao: "Histórico dedicado da produção.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: false,
      },
      {
        nome: "Históricos no Programador",
        rota: "/programador",
        descricao: "Histórico de corte e material dentro do programador.",
        perfis: ["admin", "gestao", "supervisor"],
        ativo: true,
      },
    ],
  },
  {
    grupo: "Configurações",
    itens: [
      {
        nome: "Configurações",
        rota: "/admin/configuracoes",
        descricao: "Configurações gerais em desenvolvimento.",
        perfis: ["admin"],
        ativo: false,
      },
    ],
  },
];
