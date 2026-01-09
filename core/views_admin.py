from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from django.contrib.auth.models import User
from .serializers import UserSerializer, FuenteSerializer
from .models import Fuente, TipoFuente
# Endpoint para listar y crear tipos de fuente (solo admin)
from rest_framework import status
from rest_framework import serializers

class TipoFuenteSerializer(serializers.ModelSerializer):
    class Meta:
        model = TipoFuente
        fields = ["id", "nombre", "peso", "probabilidad"]

@api_view(["GET", "POST"])
@permission_classes([IsAdminUser])
def admin_tipo_fuente(request):
    if request.method == "GET":
        tipos = TipoFuente.objects.all()
        serializer = TipoFuenteSerializer(tipos, many=True)
        return Response(serializer.data)
    elif request.method == "POST":
        serializer = TipoFuenteSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# Endpoint para listar usuarios (solo admin)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def admin_list_users(request):
    users = User.objects.all()
    serializer = UserSerializer(users, many=True)
    return Response(serializer.data)

# Puedes agregar más endpoints de administración aquí

# Endpoint para listar fuentes (solo admin)
@api_view(["GET"])
@permission_classes([IsAdminUser])
def admin_list_fuentes(request):
    fuentes = Fuente.objects.select_related('tipo').all()
    serializer = FuenteSerializer(fuentes, many=True)
    return Response(serializer.data)

# Endpoint para editar fuente (solo admin)
@api_view(["PUT"])
@permission_classes([IsAdminUser])
def admin_edit_fuente(request, fuente_id):
    fuente = Fuente.objects.get(id=fuente_id)
    serializer = FuenteSerializer(fuente, data=request.data, partial=True)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data)
    return Response(serializer.errors, status=400)
