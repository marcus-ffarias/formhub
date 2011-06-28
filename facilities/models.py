from django.db import models
from collections import defaultdict
import datetime
import json
import re

from nga_districts.models import LGA


class Facility(models.Model):
    """
    TODO: Figure out what fields should actually be on a facility. I think all
    fields should be stored in data records, with convenience fields stored in
    the facility model as needed.
    """
    facility_id = models.CharField(max_length=100)
    lga = models.ForeignKey(LGA, related_name="facilities", null=True)

    def set(self, variable, value, date=None):
        if date is None:
            date = datetime.date.today()
        d, created = FacilityRecord.objects.get_or_create(variable=variable, facility=self, date=date)
        d.value = variable.get_casted_value(value)
        d.save()

    def get_all_data(self):
        records = FacilityRecord.objects.filter(facility=self)
        d = defaultdict(dict)
        for record in records:
            d[record.variable.slug][record.date.isoformat()] = record.value
        return d

    @property
    def sector(self):
        try:
            return FacilityRecord.objects.get(facility=self, variable__slug='sector').value
        except FacilityRecord.DoesNotExist:
            return None

    def get_latest_data(self):
        records = FacilityRecord.objects.filter(facility=self).order_by('-date')
        d = {}
        for r in records:
            # todo: test to make sure this sorting is correct
            if r.variable.slug not in d:
                d[r.variable.slug] = r.value
        return d

    def get_latest_value_for_variable(self, variable):
        if type(variable) == str:
            variable = Variable.objects.get(slug=variable)
        try:
            record = FacilityRecord.objects.filter(facility=self, variable=variable).order_by('-date')[0]
        except IndexError:
            return None
        return record.value

    def set_value(self, variable, value):
        d, created = FacilityRecord.objects.get_or_create(variable=variable, facility=self)
        d.value = Variable.get_casted_value(value)
        d.save()

    def dates(self):
        """
        Return a list of dates of all observations for this facility.
        """
        drs = FacilityRecord.objects.filter(facility=self).values('date').distinct()
        return [d['date'] for d in drs]

    @classmethod
    def get_latest_data_by_lga(cls, lga):
        d = defaultdict(dict)
#        records = FacilityRecord.objects.filter(facility__lga=lga).order_by('variable__slug', '-date')
        records = FacilityRecord.objects.filter(facility__lga=lga).order_by('-date')
        for r in records:
            # todo: test to make sure this sorting is correct
#            if r.variable.slug not in d[r.facility.id]:
#                d[r.facility.id][r.variable.slug] = r.value
            if r.variable_id not in d[r.facility_id]:
                d[r.facility_id][r.variable_id] = r.value
        return d


class Variable(models.Model):
    name = models.CharField(max_length=64)
#    slug = models.CharField(max_length=64, unique=True)
    slug = models.CharField(max_length=64, primary_key=True)
    data_type = models.CharField(max_length=20)
    description = models.CharField(max_length=255)

    FIELDS = ['name', 'slug', 'data_type', 'description']

    def get_casted_value(self, value):
        """
        Takes a Variable and a value and casts it to the appropriate Variable.data_type.
        """
        def get_float(x):
            return float(x)

        def get_boolean(x):
            if isinstance(x, basestring):
                regex = re.compile('(true|t|yes|y|1)', re.IGNORECASE)
                return regex.search(value) is not None
            return bool(x)

        def get_string(x):
            return unicode(x)

        cast_function = {
            'float': get_float,
            'boolean': get_boolean,
            'string': get_string
            }
        if self.data_type not in cast_function:
            raise Exception(self.__unicode__())
        return cast_function[self.data_type](value)

    def calculate_total_for_lga(self, lga):
        if self.data_type == "string":
            return None
        else:
            records = FacilityRecord.objects.filter(variable=self, facility__lga=lga)
            tot = 0
            for record in records:
                tot += record.value
            return tot

    def calculate_average_for_lga(self, lga):
        if self.data_type == "string":
            return None
        else:
            records = FacilityRecord.objects.filter(variable=self, facility__lga=lga)
            count = records.count()
            if count == 0:
                return 0
            tot = 0
            for record in records:
                tot += record.value
            return tot / count

    def to_dict(self):
        return dict([(k, getattr(self, k)) for k in self.FIELDS])

    def __unicode__(self):
        return json.dumps(self.to_dict(), indent=4)


class CalculatedVariable(Variable):
    """
    example formula: d['num_students_total'] / d['num_tchrs_total']

    Right now calculated variables will only be computed in
    FacilityBuilder.create_facility_from_dict
    """
    formula = models.TextField()

    FIELDS = Variable.FIELDS + ['formula']

    def calculate_value(self, d):
        # TODO: eval lol
        val = None
        try:
            val = eval(self.formula)
        except:
            pass
        return val


class DataRecord(models.Model):
    """
    Not sure if we want to use different columns for data types or do
    some django Meta:abstract=True stuff to have different subclasses of DataRecord
    behave differently. For now, this works and is pretty clean.
    """
    float_value = models.FloatField(null=True)
    boolean_value = models.NullBooleanField()
    string_value = models.CharField(null=True, max_length=255)

    TYPES = ['float', 'boolean', 'string']

    variable = models.ForeignKey(Variable, related_name="data_records")
    date = models.DateField(null=True)

    class Meta:
        abstract = True

    def get_value(self):
        return getattr(self, self.variable.data_type + "_value")

    def set_value(self, val):
        setattr(self, self.variable.data_type + "_value", val)

    value = property(get_value, set_value)

    def date_string(self):
        if self.date is None:
            return "No date"
        else:
            return self.date.strftime("%D")


class FacilityRecord(DataRecord):
    facility = models.ForeignKey(Facility, related_name="data_records")


class KeyRename(models.Model):
    data_source = models.CharField(max_length=64)
    old_key = models.CharField(max_length=64)
    new_key = models.CharField(max_length=64)

    class Meta:
        unique_together = (("data_source", "old_key"),)

    @classmethod
    def _get_rename_dictionary(cls, data_source):
        result = {}
        for key_rename in cls.objects.filter(data_source=data_source):
            result[key_rename.old_key] = key_rename.new_key
        return result

    @classmethod
    def rename_keys(cls, d):
        """
        Apply the rename rules saved in the database to the dict
        d. Assumes that the key '_data_source' is in d.
        """
        temp = {}
        if '_data_source' not in d:
            return
        rename_dictionary = cls._get_rename_dictionary(d['_data_source'])
        for k, v in rename_dictionary.items():
            if k in d:
                temp[v] = d[k]
                del d[k]
            else:
                print "rename rule '%s' not used in data source '%s'" % \
                    (k, d['_data_source'])
        # this could overwrite keys that weren't renamed
        d.update(temp)


from xform_manager.models import Instance
from django.db.models.signals import post_save
from facility_builder import FacilityBuilder

def create_facility_from_signal(sender, **kwargs):
    survey_instance = kwargs["instance"]
    FacilityBuilder.create_facility_from_instance(survey_instance)

post_save.connect(create_facility_from_signal, sender=Instance)
