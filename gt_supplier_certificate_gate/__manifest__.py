{
    'name': 'Supplier Certificate Gate',
    'version': '20.0.1.0.0',
    'author': 'Golok Technology',
    'license': 'OPL-1',
    'category': 'Supply Chain/Purchase',
    'sequence': 5,
    'summary': 'Company-specific supplier certificate configuration and restricted metadata',
    'depends': ['purchase', 'mail'],
    'data': ['security/groups.xml', 'security/ir.model.access.csv', 'security/rules.xml', 'views/certificates.xml'],
    'application': True,
    'installable': True,
}
