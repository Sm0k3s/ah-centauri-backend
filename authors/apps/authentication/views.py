import jwt
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import (force_bytes,
                                   force_text, )
from django.utils.http import (urlsafe_base64_encode,
                               urlsafe_base64_decode, )
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.generics import (RetrieveUpdateAPIView,
                                     CreateAPIView, )
from rest_framework.permissions import (AllowAny,
                                        IsAuthenticated, )
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from social_core.backends.oauth import (BaseOAuth1,
                                        BaseOAuth2, )
from social_core.exceptions import MissingBackend
from social_django.utils import (load_backend,
                                 load_strategy, )

from .backends import email_activation_token
from .models import (User,
                     PasswordReset, )
from .renderers import UserJSONRenderer
from .response_messages import PASSWORD_RESET_MSGS
from .serializers import (
    LoginSerializer,
    RegistrationSerializer,
    UserSerializer,
    PasswordResetSerializer,
    PasswordResetRequestSerializer,
    SetNewPasswordSerializer,
    NotificationSerializer,
    UserNotificationSerializer,
    GoogleAuthAPISerializer,
    FacebookAuthAPISerializer,
    TwitterAuthAPISerializer,
)
from .utils import (PasswordResetTokenHandler,
                    validate_image, )


class RegistrationAPIView(APIView):
    # Allow any user (authenticated or not) to hit this endpoint.
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = RegistrationSerializer

    @swagger_auto_schema(request_body=RegistrationSerializer,
                         responses={
                             201: UserSerializer()})
    def post(self, request):
        user = request.data.get('user', {})

        # The create serializer, validate serializer, save serializer pattern
        # below is common and you will see it a lot throughout this course and
        # your own work later on. Get familiar with it.
        serializer = self.serializer_class(data=user)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        token = serializer.instance.token

        # Send a verification email to the user
        # The combination of the token and uidb64 makes sure that the user
        # has a unique verification link that expires in 7 days by default
        subject = "Email Verification"
        self._kwargs = {
            'uidb64': urlsafe_base64_encode(force_bytes(user.pk)),
            'token': email_activation_token.make_token(user)
        }

        url = self.get_email_verification_url(request)

        context = {'username': user.username,
                   'url': url}
        message = render_to_string('verify.html', context)
        recipients = [user.email, ]
        msg = EmailMultiAlternatives(
            subject, message, 'ah.centauri@gmail.com', recipients)
        msg.attach_alternative(message, "text/html")
        msg.send()

        return Response({
            "token": token,
            "message": f"A verification email has been sent to {user.email}",
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)

    def get_email_verification_url(self, request):

        base_url = settings.EMAIL_VERIFICATION_BASE_URL

        uid = self._kwargs.get('uidb64')
        token = self._kwargs.get('token')

        if base_url:
            return f"{request.scheme}://{base_url}/{token}/{uid}"

        verification_url = reverse(
            'authentication:verify', kwargs=self._kwargs)

        return f"{request.scheme}://{request.get_host()}{verification_url}"


class VerifyEmailView(APIView):
    def get(self, request, uidb64, token):
        try:
            uid = force_text(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
            return Response({"message": "Invalid verification link"
                             }, status=status.HTTP_404_NOT_FOUND)
        if user is not None and email_activation_token.check_token(user, token):
            user.is_verified = True
            user.save()
            return Response({"message": "Email successfully verified"
                             }, status=status.HTTP_202_ACCEPTED)
        else:
            return Response({"message": "Verification link has expired"
                             }, status=status.HTTP_403_FORBIDDEN)


class LoginAPIView(APIView):
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = LoginSerializer

    @swagger_auto_schema(request_body=LoginSerializer,
                         responses={
                             200: UserSerializer()})
    def post(self, request):
        user = request.data.get('user', {})

        # Notice here that we do not call `serializer.save()` like we did for
        # the registration endpoint. This is because we don't actually have
        # anything to save. Instead, the `validate` method on our serializer
        # handles everything we need.
        serializer = self.serializer_class(data=user)
        serializer.is_valid(raise_exception=True)
        user_object = serializer.validated_data['user']
        token = user_object.token
        return Response({
            'token': token,
            'message': "you have successfully logged in!"
        }, status=status.HTTP_200_OK)


class UserRetrieveUpdateAPIView(RetrieveUpdateAPIView):
    permission_classes = (IsAuthenticated,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = UserSerializer

    def retrieve(self, request, *args, **kwargs):
        # There is nothing to validate or save here. Instead, we just want the
        # serializer to handle turning our `User` object into something that
        # can be JSONified and sent to the client.
        serializer = self.serializer_class(
            request.user, context={'request': request})

        return Response(serializer.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(query_serializer=RegistrationSerializer,
                         responses={
                             200: UserSerializer()})
    def update(self, request, *args, **kwargs):
        # serializer_data = request.data.get('user', {})

        image = self.request.data.get('image')
        validate_image(image)

        serializer_data = request.data
        user_data = {
            'username': serializer_data.get('username', request.user.username),
            'email': serializer_data.get('email', request.user.email),
            'profile': {
                'first_name': serializer_data.get(
                    'first_name', request.user.profile.last_name),
                'last_name': serializer_data.get(
                    'last_name', request.user.profile.last_name),
                'birth_date': serializer_data.get(
                    'birth_date', request.user.profile.birth_date),
                'bio': serializer_data.get('bio', request.user.profile.bio),
                'image': serializer_data.get(
                    'image', request.user.profile.image),
                'city': serializer_data.get(
                    'city', request.user.profile.city),
                'country': serializer_data.get(
                    'country', request.user.profile.country),
                'phone': serializer_data.get(
                    'phone', request.user.profile.phone),
                'website': serializer_data.get(
                    'website', request.user.profile.website),

            }
        }

        # Here is that serialize, validate, save pattern we talked about
        # before.
        serializer = self.serializer_class(
            # request.user, data=serializer_data, partial=True
            request.user, data=user_data, partial=True

        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)


class PasswordResetAPIView(APIView):
    """
    A view class used to send password reset email links
    """

    permission_classes = (AllowAny,)

    @swagger_auto_schema(request_body=PasswordResetRequestSerializer,
                         responses={
                             200: PasswordResetRequestSerializer()})
    def post(self, request):
        """
        Create a password reset link and send it to the user who requested it.
        View method user to send the password reset link to a user's email address

        Params
        -------
        request: Object with request data and functions

        Returns
        --------
        Response object:
            {
                "message": "message body"
            }
            OR
            {
                "errors": "error details body"
            }
        """

        # Get the user email from the request details in the "user dictionary"
        user = request.data.get('user', {})

        # Verify the email provided in the request is valid or raise an exception otherwise.
        reset_request_serializer = PasswordResetRequestSerializer(data=user)
        reset_request_serializer.is_valid(raise_exception=True)

        # Try and send the email to a user on the platform with the given email.
        try:
            # Get user based on the email if the user exists
            user_found = User.objects.get(email=user['email'])

            # Create a jwt token based on the user making the request we will use it in the reset link
            token = PasswordResetTokenHandler().get_reset_token(user['email'])
            # Validate the new PasswordReset record and raise an exception if it is not
            serializer = PasswordResetSerializer(
                data={
                    "user_id": user_found.id,
                    "token": token,
                }
            )
            serializer.is_valid(raise_exception=True)

            # Save the PasswordToken record if everything is in order
            serializer.save()

            # Send a password reset link to the user's email
            PasswordResetTokenHandler.send_reset_password_link(
                token,
                user_found,
                request
            )
            # Respond with a success message and status code if the request has passed
            return Response({"message": PASSWORD_RESET_MSGS['SENT_RESET_LINK']},
                            status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            # Send a response with an error if the user was not found.
            msg = PASSWORD_RESET_MSGS['SENT_RESET_LINK']
            return Response(
                {"errors": msg},
                status=status.HTTP_400_BAD_REQUEST
            )


class SetPasswordAPIView(APIView):
    """
    View used to change a users password when given a password reset token

    """
    permission_classes = (AllowAny,)

    @swagger_auto_schema(request_body=SetNewPasswordSerializer,
                         responses={
                             200: SetNewPasswordSerializer()})
    def patch(self, request, reset_token):
        """
        Create a password reset link and send it to the user who requested it.
        View method user to send the password reset link to a user's email address

        Params
        -------
        request: Object with request data and functions
        reset_token: String required to successfully reset the password

        Returns
        --------
        Response object:
            {
                "message": "message body"
            }
            OR
            {
                "errors": "error details body"
            }
        """

        # Set the token to the parameter from the request
        password_reset_token = reset_token

        # Get the new password and confirmed password from within the "password_data" dictionary
        password_change = request.data.get('password_data', {})

        # Check if the new_password and confirmed password both match otherwise return an error.
        if password_change['new_password'] != password_change['confirm_password']:
            return Response(
                {"errors": PASSWORD_RESET_MSGS['UNMATCHING_PASSWORDS']},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check if the password provided passes the validation requirements
        # 1 uppercase, 1 lowercase and a special character.

        set_password_serializer = SetNewPasswordSerializer(
            data={"password": password_change['new_password']}
        )
        # Raise an exception if the validation does not pass
        set_password_serializer.is_valid(raise_exception=True)

        # Check if there is a value in the current password reset token
        if password_reset_token is not None:

            # Try to decode the token provided
            try:
                user_data = jwt.decode(
                    password_reset_token, settings.SECRET_KEY, algorithms=['HS256'])
            except Exception as e:
                return Response(
                    {"errors": PASSWORD_RESET_MSGS['EXPIRED_LINK']},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Try to fetch the password reset record related to the token,
            # from the PasswordReset table in the database (if the record exists)
            try:
                link_password_reset_record = PasswordReset.objects.get(
                    token=password_reset_token)
                # Check if the password reset record of the token has been used before and throw and error if so
                if link_password_reset_record.used is True:
                    return Response(
                        {"errors": PASSWORD_RESET_MSGS['USED_RESET_LINK']},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response(
                    {"errors": PASSWORD_RESET_MSGS['INVALID_RESET_LINK']},
                    status=status.HTTP_400_BAD_REQUEST
                )

            # Try to fetch the user data from the decode token payload email.
            # This is so we can reset their password and give them a new one.
            try:
                # find the user for the request and save their new password
                user_found = User.objects.get(email=user_data['user_email'])
                user_found.set_password(password_change["new_password"])
                user_found.save()
                # Update and save the Password Reset record
                # so the token associated with it can't be used again.
                password_reset_record = PasswordReset.objects.get(
                    token=password_reset_token)
                password_reset_record.used = True
                password_reset_record.save()
                # Let the user know the password reset was successful
                return Response(
                    {"message": PASSWORD_RESET_MSGS['RESET_SUCCESSFUL']},
                    status=status.HTTP_200_OK
                )
            except Exception as e:
                msg = "The user with email {} could not be found".format(
                    user_data['user_email']
                )
                return Response(
                    {"errors": msg},
                    status=status.HTTP_400_BAD_REQUEST
                )


class NotificationsView(APIView):
    """
    View used to show or retrieve the authenticated user's notifications
    and to mark them as read
    """
    permission_classes = (IsAuthenticated,)
    pagination_class = PageNumberPagination

    def get(self, request):
        notifications = request.user.notifications.all()

        paginator = PageNumberPagination()
        page = paginator.paginate_queryset(notifications, request)

        notifications = NotificationSerializer(
            page, many=True, context={'request': request})

        return paginator.get_paginated_response(notifications.data)

    @swagger_auto_schema(query_serializer=NotificationSerializer,
                         responses={
                             200: NotificationSerializer()})
    def patch(self, request):
        request.user.notifications.update(is_read=True)

        notifications = request.user.notifications

        notifications = NotificationSerializer(
            instance=notifications,
            many=True,
            context={'request': request}
        )

        return Response(notifications.data)


class NotificationSettingsView(APIView):
    """
    View used to opt in/out of app notifications.
    These notifications currently include in app & email notifications
    """
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        notification_settings = request.user.notification_settings

        notification_settings = UserNotificationSerializer(
            instance=notification_settings,
            context={'request': request}
        )

        notification_settings = notification_settings.data

        return Response(notification_settings)

    @swagger_auto_schema(query_serializer=UserNotificationSerializer,
                         responses={
                             200: UserNotificationSerializer()})
    def patch(self, request):
        notification_settings = request.user.notification_settings
        serializer = UserNotificationSerializer(
            notification_settings, data=request.data)
        serializer.is_valid(raise_exception=True)
        notification_settings = serializer.save(user=request.user)
        notification_settings = UserNotificationSerializer(
            instance=notification_settings,
            context={'request': request})

        return Response(notification_settings.data)


class GoogleAuthAPIView(APIView):
    """
    Manage Google Login
    """
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = GoogleAuthAPISerializer

    def post(self, request):
        """
        Create a user is not exist
        Retrieve and return authenticated user token

        :param request:
        :return: token
        """
        serializer = self.serializer_class(data=request.data.get('google', {}))
        serializer.is_valid(raise_exception=True)
        return Response({
            'token': serializer.data.get('access_token')
        }, status=status.HTTP_200_OK)


class FacebookAuthAPIView(APIView):
    """
    Manage Facebook Login
    """
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = FacebookAuthAPISerializer

    def post(self, request):
        """
        Create a user is not exist
        Retrieve and return authenticated user token

        :param request:
        :return: token
        """
        serializer = self.serializer_class(
            data=request.data.get('facebook', {}))
        serializer.is_valid(raise_exception=True)
        return Response({
            'token': serializer.data.get('access_token')
        }, status=status.HTTP_200_OK)


class TwitterAuthAPIView(APIView):
    """
    Manage Twitter Login
    """
    permission_classes = (AllowAny,)
    renderer_classes = (UserJSONRenderer,)
    serializer_class = TwitterAuthAPISerializer

    def post(self, request):
        """
        Create a user is not exist
        Retrieve and return authenticated user token

        :param request:
        :return: token
        """
        serializer = self.serializer_class(
            data=request.data.get('twitter', {}))
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data['token']
        return Response({"token": token}, status=status.HTTP_200_OK)
