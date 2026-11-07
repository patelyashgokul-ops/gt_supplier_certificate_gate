{
    'name': 'Supplier Certificate Gate',
    'version': '20.0.1.0.0',
    'author': 'Golok Technology',
    'license': 'OPL-1',
    'category': 'Supply Chain/Purchase',
    'sequence': 5,
    'summary': 'Reviewer-controlled certificates, purchase gates and renewal follow-up',
    'depends': ['purchase', 'mail'],
    'data': ['security/groups.xml', 'security/ir.access.csv', 'views/certificates.xml', 'views/lifecycle.xml', 'views/purchase_gate.xml', 'data/renewal.xml', 'views/renewal.xml'],
    'application': True,
    'installable': True,
}
