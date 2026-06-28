# -*- coding: utf-8 -*-
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, BooleanField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length, Regexp


class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[DataRequired()])
    remember = BooleanField('Recordarme')
    submit = SubmitField('Iniciar sesión')


class RegisterForm(FlaskForm):
    username = StringField('Nombre', validators=[DataRequired(), Length(2, 80)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Contraseña', validators=[
        DataRequired(),
        Length(8, 128, message='Mínimo 8 caracteres'),
        Regexp(r'(?=.*[A-Z])(?=.*\d)', message='Debe tener al menos una mayúscula y un número'),
    ])
    confirm = PasswordField('Confirmar contraseña', validators=[
        DataRequired(), EqualTo('password', message='Las contraseñas no coinciden')
    ])
    submit = SubmitField('Crear cuenta')


class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Enviar enlace')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('Nueva contraseña', validators=[
        DataRequired(),
        Length(8, 128),
        Regexp(r'(?=.*[A-Z])(?=.*\d)', message='Debe tener al menos una mayúscula y un número'),
    ])
    confirm = PasswordField('Confirmar contraseña', validators=[
        DataRequired(), EqualTo('password', message='Las contraseñas no coinciden')
    ])
    submit = SubmitField('Cambiar contraseña')


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Contraseña actual', validators=[DataRequired()])
    new_password = PasswordField('Nueva contraseña', validators=[
        DataRequired(), Length(8, 128),
        Regexp(r'(?=.*[A-Z])(?=.*\d)', message='Debe tener al menos una mayúscula y un número'),
    ])
    confirm = PasswordField('Confirmar nueva contraseña', validators=[
        DataRequired(), EqualTo('new_password', message='Las contraseñas no coinciden')
    ])
    submit = SubmitField('Cambiar contraseña')
