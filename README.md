# LinkedAdminReadonlyField
Django admin extension.
Adds links to read only ForeignKey or OneToOne admin fields if possible.

## Installation:
```
pip install git+https://github.com/ooppsss60/LinkedAdminReadonlyField
```

## Usage:

```
from linked_read_only_field import LinkedModelAdmin

class MyModelAdmin(LinkedModelAdmin):
    fields = ('user', ...)
    readonly_fields = ('user', ...)
```
