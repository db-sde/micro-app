from schemas.university import (
    UniversitySchema,
    UNIVERSITY_FIELDS,
    UNIVERSITY_FIELD_TYPES,
    UNIVERSITY_REQUIRED,
)
from schemas.course import (
    CourseSchema,
    COURSE_FIELDS,
    COURSE_FIELD_TYPES,
    COURSE_REQUIRED,
)
from schemas.specialization import (
    SpecializationSchema,
    SPECIALIZATION_FIELDS,
    SPECIALIZATION_FIELD_TYPES,
    SPECIALIZATION_REQUIRED,
)

FIELDS_BY_TYPE = {
    "university": UNIVERSITY_FIELDS,
    "course": COURSE_FIELDS,
    "specialization": SPECIALIZATION_FIELDS,
}

FIELD_TYPES_BY_TYPE = {
    "university": UNIVERSITY_FIELD_TYPES,
    "course": COURSE_FIELD_TYPES,
    "specialization": SPECIALIZATION_FIELD_TYPES,
}

REQUIRED_BY_TYPE = {
    "university": UNIVERSITY_REQUIRED,
    "course": COURSE_REQUIRED,
    "specialization": SPECIALIZATION_REQUIRED,
}
